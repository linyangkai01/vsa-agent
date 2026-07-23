param(
    [int]$ApiPort = 8000,
    [int]$EsPort = 9200,
    [int]$UiPort = 3000,
    [string]$Index = "vsa-video-embeddings",
    [string]$CondaEnv = "",
    [string]$DataRoot = "",
    [string]$Config = "config.yaml",
    [string]$SecretsFile = "",
    [int]$TimeoutSec = 90,
    [switch]$StopElasticsearch,
    [switch]$SmokeOnly,
    [switch]$Validate,
    [switch]$KeepRunning,
    [switch]$ProbeProviders
)

$ErrorActionPreference = "Stop"
$explicitValidation = $Validate.IsPresent
if ($KeepRunning -and $SmokeOnly) {
    throw "-KeepRunning cannot be combined with -SmokeOnly"
}
if ($KeepRunning -and -not $explicitValidation) {
    throw "-KeepRunning requires explicit validation via -Validate"
}
if ($ProbeProviders -and ($Validate -or $SmokeOnly -or $KeepRunning)) {
    throw "-ProbeProviders cannot be combined with validation or keep-running modes"
}
$Validate = $Validate -or $SmokeOnly
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot ".runtime\es-stack"
$runsDir = Join-Path $runtimeDir "runs"
$runId = [guid]::NewGuid().ToString()
$runDir = Join-Path $runsDir $runId
$latestLink = Join-Path $runtimeDir "latest"
$configPath = Join-Path $runDir "config.yaml"
$validationConfigPath = Join-Path $runDir "validation-config.yaml"
$stackLogPath = Join-Path $runDir "stack.log"
$apiLogPath = Join-Path $runDir "api.log"
$workerLogPath = Join-Path $runDir "worker.log"
$uiLogPath = Join-Path $runDir "ui.log"
$esLogPath = Join-Path $runDir "es.log"
$processManifestPath = Join-Path $runDir "processes.json"
$apiUrl = "http://127.0.0.1:$ApiPort"
$apiHealthUrl = "$apiUrl/health"
$uiUrl = "http://127.0.0.1:$UiPort"
$esEndpoint = "http://127.0.0.1:$EsPort"
$validationIndex = "validation-$runId"
$validationSmokeIndex = "$validationIndex-legacy-smoke"
$validationDataRoot = Join-Path $runDir $validationIndex
$apiConfigPath = $configPath
$apiProcess = $null
$workerProcess = $null
$uiProcess = $null
$esLogProcess = $null
$esStartedByRun = $false
$manifest = [ordered]@{ run_id = $runId; processes = @() }
$oldVsaConfig = $env:VSA_CONFIG
$oldPythonPath = $env:PYTHONPATH
$oldSearchTab = $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB
$oldAgentApiUrl = $env:NEXT_PUBLIC_AGENT_API_URL_BASE
$oldVstApiUrl = $env:NEXT_PUBLIC_VST_API_URL
$oldInternalAgentApiUrl = $env:VSA_INTERNAL_AGENT_API_URL_BASE
$oldUiPort = $env:PORT
$secretEnvironmentSnapshot = @{}
$secretsFileExplicit = $PSBoundParameters.ContainsKey("SecretsFile")
if ([string]::IsNullOrWhiteSpace($SecretsFile)) {
    $SecretsFile = if ([string]::IsNullOrWhiteSpace($env:VSA_SECRETS_FILE)) {
        Join-Path $HOME ".config\vsa-agent\secrets.env"
    } else {
        $env:VSA_SECRETS_FILE
    }
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
foreach ($path in @($stackLogPath, $apiLogPath, $workerLogPath, $uiLogPath, $esLogPath)) {
    [System.IO.File]::WriteAllText($path, "")
}
if (Test-Path -LiteralPath $latestLink) {
    $latestItem = Get-Item -LiteralPath $latestLink -Force
    if ($latestItem.PSIsContainer -and -not ($latestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "LATEST_POINTER_CONFLICT: refusing to replace directory $latestLink"
    }
    Remove-Item -LiteralPath $latestLink -Force
}
New-Item -ItemType Junction -Path $latestLink -Target $runDir | Out-Null

function Write-Stack {
    param([string]$Message, [switch]$ErrorLine)
    $protected = Protect-RuntimeText $Message
    [VsaRuntimeLogPump]::PublishProtected("", $stackLogPath, "[stack]", $protected, $ErrorLine.IsPresent)
}

function Protect-RuntimeText {
    param([AllowEmptyString()][string]$Text)
    if (-not ("VsaRuntimeLogPump" -as [type])) {
        $sourcePath = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
            Join-Path (Get-Location) "scripts\\lib\\RuntimeLogPump.cs"
        } else {
            Join-Path $PSScriptRoot "lib\\RuntimeLogPump.cs"
        }
        Add-Type -Path $sourcePath
    }
    return [VsaRuntimeLogPump]::ProtectText($Text)
}

function Import-PrivateSecretsFile {
    param([string]$Path, [bool]$Explicit)
    if (-not (Test-Path -LiteralPath $Path)) {
        if ($Explicit) { throw "secrets file does not exist: $Path" }
        return
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "secrets file must be a readable regular file: $Path"
    }
    $acl = if ("System.IO.FileSystemAclExtensions" -as [type]) {
        [System.IO.FileSystemAclExtensions]::GetAccessControl([System.IO.FileInfo]::new($Path))
    } else {
        [System.IO.File]::GetAccessControl($Path)
    }
    $ownerSid = $acl.GetOwner([System.Security.Principal.SecurityIdentifier])
    $currentOwnerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $currentOwnerSid -or $ownerSid -ne $currentOwnerSid) {
        throw "secrets file must be owned by the current user"
    }

    $loaded = 0
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) { continue }
        if ($line -notmatch '^(?<key>[A-Z][A-Z0-9_]*_API_[K][E][Y])=(?<value>.+)$') {
            throw "secrets file contains an invalid entry"
        }
        $key = $Matches.key
        $value = $Matches.value.Trim()
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "secrets file contains an empty value for $key"
        }
        if (-not $script:secretEnvironmentSnapshot.ContainsKey($key)) {
            $script:secretEnvironmentSnapshot[$key] = @{
                Exists = Test-Path -LiteralPath "Env:$key"
                Value = [Environment]::GetEnvironmentVariable($key, "Process")
            }
        }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
        $loaded += 1
    }
    Write-Stack "loaded private secrets file path=$Path keys=$loaded"
}

function Write-ProcessManifest {
    $temporary = "$processManifestPath.tmp"
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $processManifestPath -Force
}

function Add-ManagedProcess {
    param(
        [string]$Component,
        [int]$ProcessId,
        [string]$SafeCommand
    )
    $script:manifest.processes += [ordered]@{
        component = $Component
        pid = $ProcessId
        command = $SafeCommand
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        exit_status = $null
    }
    Write-ProcessManifest
}

function Set-ProcessExit {
    param([string]$Component, [object]$ExitStatus)
    for ($index = $script:manifest.processes.Count - 1; $index -ge 0; $index--) {
        $item = $script:manifest.processes[$index]
        if ($item.component -eq $Component -and $null -eq $item.exit_status) {
            $item.exit_status = $ExitStatus
            Write-ProcessManifest
            return
        }
    }
}

Write-ProcessManifest
Write-Stack "run_id=$runId evidence=$runDir"

function ConvertTo-NativeArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Start-LoggedProcess {
    param(
        [string]$Component,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$LogPath,
        [string]$SafeCommand,
        [switch]$Record = $true
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument "$_" }) -join " ")
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $logPump = $null
    try {
        if (-not $process.Start()) { throw "Failed to start $Component" }
        $launchStartTicks = $process.StartTime.ToUniversalTime().Ticks
        $launchTicks = $launchStartTicks - ($launchStartTicks % 10)
        $process | Add-Member -NotePropertyName VsaLaunchIdentity -NotePropertyValue ([pscustomobject]@{
            ProcessId = $process.Id
            StartTicks = $launchStartTicks
            CreationKey = $launchTicks.ToString([Globalization.CultureInfo]::InvariantCulture)
            CreationTicks = $launchTicks
        })
        $process | Add-Member -NotePropertyName VsaProcessTracker -NotePropertyValue ([pscustomobject]@{
            Component = $Component
            OwnedByPid = @{}
        })
        $logPump = [VsaRuntimeLogPump]::new(
            $process.StandardOutput,
            $process.StandardError,
            $LogPath,
            $stackLogPath,
            "[$Component]"
        )
        $process | Add-Member -NotePropertyName VsaLogPump -NotePropertyValue $logPump
        if ($Record) {
            Add-ManagedProcess -Component $Component -ProcessId $process.Id -SafeCommand $SafeCommand
        }
        return $process
    } catch {
        try {
            if (-not $process.HasExited) {
                $process.Kill()
                $process.WaitForExit()
            }
        } catch { }
        try {
            if ($null -ne $logPump) { $logPump.Complete(5000) }
        } catch { }
        try {
            if ($null -ne $logPump) { $logPump.Dispose() }
        } catch { }
        try { $process.Dispose() } catch { }
        throw
    }
}

function Invoke-StackCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Stack "$_" }
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Assert-CurrentUserProcess {
    param(
        [int]$ProcessId,
        [object]$ExpectedCreationDate = $null,
        [object]$ExpectedExecutablePath = $null,
        [object]$ExpectedCommandLine = $null
    )
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        throw "FOREIGN_LISTENER: refusing to terminate PID $ProcessId because process lookup failed"
    }
    try {
        $owner = Invoke-CimMethod -InputObject $processInfo -MethodName GetOwner -ErrorAction Stop
    } catch {
        throw "FOREIGN_LISTENER: refusing to terminate PID $ProcessId because owner lookup failed"
    }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $identityParts = $identity.Split("\", 2)
    $expectedDomain = if ($identityParts.Count -eq 2) { $identityParts[0] } else { $env:COMPUTERNAME }
    $expectedUser = if ($identityParts.Count -eq 2) { $identityParts[1] } else { $identityParts[0] }
    if (
        $owner.ReturnValue -ne 0 -or
        [string]::IsNullOrWhiteSpace($owner.User) -or
        [string]::IsNullOrWhiteSpace($owner.Domain) -or
        $owner.User -ine $expectedUser -or
        $owner.Domain -ine $expectedDomain
    ) {
        throw "FOREIGN_LISTENER: refusing to terminate PID $ProcessId owned by another user"
    }
    if ($null -ne $ExpectedCreationDate -and $processInfo.CreationDate -ne $ExpectedCreationDate) {
        throw "PID_REUSED: refusing to terminate PID $ProcessId because its identity changed"
    }
    if (
        ($PSBoundParameters.ContainsKey('ExpectedExecutablePath') -and $processInfo.ExecutablePath -ne $ExpectedExecutablePath) -or
        ($PSBoundParameters.ContainsKey('ExpectedCommandLine') -and $processInfo.CommandLine -ne $ExpectedCommandLine)
    ) {
        throw "PID_REUSED: refusing to terminate PID $ProcessId because its identity changed"
    }
    return $processInfo
}

function Wait-PortFree {
    param([int]$Port, [int]$TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0) {
        if ((Get-Date) -ge $deadline) { throw "Port $Port was not released within $TimeoutSec seconds" }
        Start-Sleep -Milliseconds 500
    }
}

function Reclaim-Port {
    param([int]$Port, [int]$TimeoutSec)
    $owners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($ownerPid in $owners) {
        $ownedProcess = Assert-CurrentUserProcess -ProcessId $ownerPid
        $process = $null
        try {
            $process = Get-Process -Id $ownerPid -ErrorAction Stop
            $process.Refresh()
            if ($process.HasExited) {
                throw "PID_REUSED: refusing to terminate PID $ownerPid because its process handle exited"
            }
            $startTicks = $process.StartTime.ToUniversalTime().Ticks
            Assert-CurrentUserProcess -ProcessId $ownerPid `
                -ExpectedCreationDate $ownedProcess.CreationDate `
                -ExpectedExecutablePath $ownedProcess.ExecutablePath `
                -ExpectedCommandLine $ownedProcess.CommandLine | Out-Null
            $process.Refresh()
            if ($process.HasExited -or $process.StartTime.ToUniversalTime().Ticks -ne $startTicks) {
                throw "PID_REUSED: refusing to terminate PID $ownerPid because its process handle identity changed"
            }
            Write-Stack "reclaiming port $Port from current-user PID $ownerPid"
            $process.Kill()
            $process.WaitForExit()
        } finally {
            if ($null -ne $process) { $process.Dispose() }
        }
    }
    Wait-PortFree -Port $Port -TimeoutSec $TimeoutSec
}

function ConvertTo-TrackedProcessIdentity {
    param([object]$ProcessInfo, [int]$Depth)
    if ($null -eq $ProcessInfo -or $null -eq $ProcessInfo.CreationDate) { return $null }
    try {
        $creationTicks = ([datetime]$ProcessInfo.CreationDate).ToUniversalTime().Ticks
    } catch {
        return $null
    }
    $executablePath = [string]$ProcessInfo.ExecutablePath
    $commandLine = [string]$ProcessInfo.CommandLine
    if (
        [string]::IsNullOrWhiteSpace($executablePath) -or
        [string]::IsNullOrWhiteSpace($commandLine)
    ) {
        return $null
    }
    $creationTicks -= $creationTicks % 10
    return [pscustomobject]@{
        ProcessId = [int]$ProcessInfo.ProcessId
        ParentProcessId = [int]$ProcessInfo.ParentProcessId
        CreationKey = $creationTicks.ToString([Globalization.CultureInfo]::InvariantCulture)
        CreationTicks = $creationTicks
        ExecutablePath = $executablePath
        CommandLine = $commandLine
        Depth = $Depth
    }
}

function Test-TrackedProcessIdentity {
    param([object]$Expected, [object]$Current)
    if ($null -eq $Expected -or $null -eq $Current) { return $false }
    $currentIdentity = ConvertTo-TrackedProcessIdentity -ProcessInfo $Current -Depth ([int]$Expected.Depth)
    if ($null -eq $currentIdentity) { return $false }
    return (
        [int]$Expected.ProcessId -eq [int]$currentIdentity.ProcessId -and
        [int]$Expected.ParentProcessId -eq [int]$currentIdentity.ParentProcessId -and
        [string]$Expected.CreationKey -ceq [string]$currentIdentity.CreationKey -and
        [string]$Expected.ExecutablePath -ceq [string]$currentIdentity.ExecutablePath -and
        [string]$Expected.CommandLine -ceq [string]$currentIdentity.CommandLine
    )
}

function Update-ProcessTracker {
    param(
        [System.Diagnostics.Process]$Process,
        [AllowEmptyCollection()][object[]]$Snapshot
    )
    if ($null -eq $Process) { return }
    $trackerProperty = $Process.PSObject.Properties["VsaProcessTracker"]
    if ($null -eq $trackerProperty -or $null -eq $trackerProperty.Value) { return }
    $launchProperty = $Process.PSObject.Properties["VsaLaunchIdentity"]
    if ($null -eq $launchProperty -or $null -eq $launchProperty.Value) {
        throw "Process tracker root launch identity is unavailable"
    }

    $tracker = $trackerProperty.Value
    $ownedByPid = $tracker.OwnedByPid
    $snapshot = if ($PSBoundParameters.ContainsKey("Snapshot")) {
        @($Snapshot)
    } else {
        @(Get-CimInstance Win32_Process -ErrorAction Stop)
    }
    if ($snapshot.Count -eq 0) {
        throw "Process tracker snapshot is empty"
    }
    $snapshotByPid = @{}
    foreach ($processInfo in $snapshot) {
        if ($null -ne $processInfo) {
            $snapshotByPid["$([int]$processInfo.ProcessId)"] = $processInfo
        }
    }

    if ($ownedByPid.Count -eq 0) {
        $rootInfo = $snapshotByPid["$($Process.Id)"]
        $rootIdentity = ConvertTo-TrackedProcessIdentity -ProcessInfo $rootInfo -Depth 0
        $launchIdentity = $launchProperty.Value
        if (
            $null -eq $rootIdentity -or
            [int]$launchIdentity.ProcessId -ne [int]$rootIdentity.ProcessId -or
            $null -eq $launchIdentity.StartTicks
        ) {
            throw "Process tracker root identity could not be verified"
        }
        try {
            $null = $Process.Handle
            $Process.Refresh()
            if ($Process.HasExited) { throw "root exited" }
            $rootStartTicks = $Process.StartTime.ToUniversalTime().Ticks
        } catch {
            throw "Process tracker root identity could not be verified"
        }
        $normalizedRootTicks = $rootStartTicks - ($rootStartTicks % 10)
        if (
            [long]$launchIdentity.StartTicks -ne [long]$rootStartTicks -or
            [long]$rootIdentity.CreationTicks -ne [long]$normalizedRootTicks
        ) {
            throw "Process tracker root identity could not be verified"
        }
        $rootIdentity | Add-Member -NotePropertyName StartTicks -NotePropertyValue ([long]$rootStartTicks)
        $rootIdentity | Add-Member -NotePropertyName BoundProcess -NotePropertyValue $Process
        $ownedByPid["$($Process.Id)"] = $rootIdentity
    }

    $added = $true
    while ($added) {
        $added = $false
        foreach ($candidate in $snapshot) {
            if ($null -eq $candidate) { continue }
            $candidatePid = [int]$candidate.ProcessId
            if ($ownedByPid.ContainsKey("$candidatePid")) { continue }
            $parent = $ownedByPid["$([int]$candidate.ParentProcessId)"]
            if ($null -eq $parent) { continue }
            $currentParent = $snapshotByPid["$([int]$candidate.ParentProcessId)"]
            if (-not (Test-TrackedProcessIdentity -Expected $parent -Current $currentParent)) { continue }
            $candidateIdentity = ConvertTo-TrackedProcessIdentity -ProcessInfo $candidate -Depth ([int]$parent.Depth + 1)
            if (
                $null -eq $candidateIdentity -or
                [long]$candidateIdentity.CreationTicks -lt [long]$parent.CreationTicks
            ) {
                continue
            }

            $boundCandidate = $null
            $accepted = $false
            try {
                $boundCandidate = Get-Process -Id $candidatePid -ErrorAction Stop
                $null = $boundCandidate.Handle
                $candidateStartTicks = $boundCandidate.StartTime.ToUniversalTime().Ticks
                if (($candidateStartTicks - ($candidateStartTicks % 10)) -ne [long]$candidateIdentity.CreationTicks) {
                    continue
                }
                $currentCandidate = Get-CimInstance Win32_Process -Filter "ProcessId=$candidatePid" -ErrorAction SilentlyContinue
                if (-not (Test-TrackedProcessIdentity -Expected $candidateIdentity -Current $currentCandidate)) {
                    continue
                }
                $boundCandidate.Refresh()
                if ($boundCandidate.HasExited) { continue }
                $candidateIdentity | Add-Member -NotePropertyName StartTicks -NotePropertyValue ([long]$candidateStartTicks)
                $candidateIdentity | Add-Member -NotePropertyName BoundProcess -NotePropertyValue $boundCandidate
                $ownedByPid["$candidatePid"] = $candidateIdentity
                $accepted = $true
                $added = $true
                $createdAt = ([datetime]$candidate.CreationDate).ToUniversalTime().ToString("o")
                Write-Stack "process tracker registered component=$($tracker.Component) pid=$candidatePid parent_pid=$([int]$candidate.ParentProcessId) creation=$createdAt"
            } catch {
                continue
            } finally {
                if (-not $accepted -and $null -ne $boundCandidate) {
                    try { $boundCandidate.Dispose() } catch { }
                }
            }
        }
    }
}

function Wait-HttpHealth {
    param([string]$Url, [int]$TimeoutSec, [System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        Update-ProcessTracker -Process $Process
        if ($Process.HasExited) { throw "FastAPI process exited before health check succeeded. ExitCode=$($Process.ExitCode)" }
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 5
            if ($response.status -eq "ok") { return }
        } catch { Start-Sleep -Seconds 2 }
    } while ((Get-Date) -lt $deadline)
    throw "FastAPI did not become reachable at $Url within $TimeoutSec seconds"
}

function Wait-WorkerReady {
    param([string]$LogPath, [int]$TimeoutSec, [System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        Update-ProcessTracker -Process $Process
        if ($Process.HasExited) { throw "Recorded-video Worker exited before readiness. ExitCode=$($Process.ExitCode)" }
        foreach ($line in @(Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue)) {
            try { $payload = $line | ConvertFrom-Json } catch { continue }
            if ($payload.event -eq "worker.readiness" -and $payload.ready -eq $true) { return }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "Recorded-video Worker did not emit ready=true within $TimeoutSec seconds"
}

function Wait-UiReady {
    param([string]$Url, [int]$TimeoutSec, [System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        Update-ProcessTracker -Process $Process
        if ($Process.HasExited) { throw "Original UI process exited before readiness. ExitCode=$($Process.ExitCode)" }
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { return }
        } catch { Start-Sleep -Seconds 2 }
    } while ((Get-Date) -lt $deadline)
    throw "Original UI did not become reachable at $Url within $TimeoutSec seconds"
}

function Wait-SameOriginProxy {
    param([string]$Url, [int]$TimeoutSec)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        try {
            Invoke-WebRequest -Uri "$Url/api/v1/search" -TimeoutSec 5 -UseBasicParsing | Out-Null
        } catch {
            if ($_.Exception.Response.StatusCode.value__ -eq 405) { return }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Same-origin API proxy did not become reachable through $Url"
}

function Write-SearchConfig {
    param(
        [string]$SourceConfig,
        [string]$TargetConfig,
        [string]$EsEndpoint,
        [string]$SelectedIndex,
        [string]$SelectedDataRoot,
        [ValidateSet("production", "validation")][string]$Mode
    )
    $validationMode = $Mode -eq "validation"
    $raw = Get-Content -Raw -LiteralPath $SourceConfig
    $mockValue = if ($validationMode) { "true" } else { "false" }
    $searchBlock = @"
search:
  enabled: true
  es_endpoint: $EsEndpoint
  embed_index: $SelectedIndex
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: $mockValue
  force_mock_embedding: $mockValue
"@
    $updated = [regex]::Replace($raw, "(?m)^search:\r?\n(?:^[ \t]+[^\r\n]*(?:\r?\n|$))*", $searchBlock + "`r`n", 1)
    $enabled = "true"
    $updated = [regex]::Replace($updated, "(?m)^(recorded_video:\r?\n[ \t]+enabled:)[ \t]*(?:true|false)", "`${1} $enabled", 1)
    $yamlDataRoot = $SelectedDataRoot | ConvertTo-Json -Compress
    $dataRootPattern = "(?m)^(recorded_video:\r?\n(?:[ \t]+.*\r?\n)*?[ \t]+data_root:)[^\r\n]*"
    $updated = [regex]::Replace($updated, $dataRootPattern, "`${1} $yamlDataRoot", 1)
    Set-Content -LiteralPath $TargetConfig -Value $updated -Encoding UTF8
}

function PythonCommand {
    param([string]$CondaEnv, [string[]]$PythonArgs)
    if ([string]::IsNullOrWhiteSpace($CondaEnv)) { return @{ File = "python"; Args = $PythonArgs } }
    return @{ File = "conda"; Args = @("run", "--no-capture-output", "-n", $CondaEnv, "python") + $PythonArgs }
}

function Ensure-UiRuntime {
    Invoke-StackCommand -FilePath "bash" -Arguments @((Join-Path $PSScriptRoot "bootstrap_node.sh"))
    $installCommand = 'set -euo pipefail; root="$1"; source "$root/.deps/node-env.sh"; cd "$root"; if [[ ! -x frontend/original-ui/node_modules/.bin/turbo ]]; then npm run ui:install; fi'
    Invoke-StackCommand -FilePath "bash" -Arguments @("-c", $installCommand, "bash", $repoRoot)
}

function Stop-OwnedProcessTree {
    param(
        [string]$Component,
        [System.Diagnostics.Process]$Process,
        [int]$GraceTimeoutMs = 5000,
        [int]$ForceTimeoutMs = 5000,
        [int]$LogDrainTimeoutMs = 5000
    )
    if ($null -eq $Process) { return }
    $exitStatus = "shutdown-failed"
    $terminationError = $null
    $finalizationErrors = [System.Collections.Generic.List[string]]::new()
    $trackerProperty = $Process.PSObject.Properties["VsaProcessTracker"]
    $ownedByPid = if ($null -ne $trackerProperty -and $null -ne $trackerProperty.Value) {
        $trackerProperty.Value.OwnedByPid
    } else {
        @{}
    }
    $launchIdentity = $null
    $launchIdentityProperty = $Process.PSObject.Properties["VsaLaunchIdentity"]
    if ($null -ne $launchIdentityProperty) {
        $launchIdentity = $launchIdentityProperty.Value
    } else {
        try {
            $launchStartTicks = $Process.StartTime.ToUniversalTime().Ticks
            $launchTicks = $launchStartTicks - ($launchStartTicks % 10)
            $launchIdentity = [pscustomobject]@{
                ProcessId = $Process.Id
                StartTicks = $launchStartTicks
                CreationKey = $launchTicks.ToString([Globalization.CultureInfo]::InvariantCulture)
                CreationTicks = $launchTicks
            }
        } catch {
            $launchIdentity = $null
        }
    }
    $registerOwnedLineage = {
        param([object[]]$Snapshot)
        $snapshotByPid = @{}
        foreach ($processInfo in @($Snapshot)) {
            if ($null -eq $processInfo) { continue }
            $snapshotByPid["$([int]$processInfo.ProcessId)"] = $processInfo
        }
        if ($ownedByPid.Count -eq 0) {
            $rootInfo = $snapshotByPid["$($Process.Id)"]
            if ($null -ne $rootInfo) {
                $rootIdentity = ConvertTo-TrackedProcessIdentity -ProcessInfo $rootInfo -Depth 0
                if (
                    $null -eq $launchIdentity -or
                    $null -eq $rootIdentity -or
                    [int]$launchIdentity.ProcessId -ne [int]$rootIdentity.ProcessId
                ) {
                    throw "Root process identity for $Component could not be verified"
                }
                if ($null -eq $launchIdentity.StartTicks) {
                    throw "Root .NET launch identity for $Component could not be verified"
                }
                try {
                    $null = $Process.Handle
                    $Process.Refresh()
                    if ($Process.HasExited) {
                        throw "Root process identity for $Component could not be verified"
                    }
                    $boundRootStartTicks = $Process.StartTime.ToUniversalTime().Ticks
                } catch {
                    throw "Root process identity for $Component could not be verified"
                }
                if ([long]$launchIdentity.StartTicks -ne [long]$boundRootStartTicks) {
                    throw "Root process identity for $Component could not be verified"
                }
                $launchKey = [string]$launchIdentity.CreationKey
                if ([string]::IsNullOrWhiteSpace($launchKey)) {
                    $launchTicks = [long]$launchIdentity.StartTicks
                    $launchKey = ($launchTicks - ($launchTicks % 10)).ToString(
                        [Globalization.CultureInfo]::InvariantCulture
                    )
                }
                if ($launchKey -cne [string]$rootIdentity.CreationKey) {
                    throw "Root process identity for $Component could not be verified"
                }
                $rootIdentity | Add-Member -NotePropertyName StartTicks -NotePropertyValue ([long]$boundRootStartTicks)
                $rootIdentity | Add-Member -NotePropertyName BoundProcess -NotePropertyValue $Process
                $ownedByPid["$($Process.Id)"] = $rootIdentity
            }
        }
        $added = $true
        while ($added) {
            $added = $false
            foreach ($candidate in @($Snapshot)) {
                if ($null -eq $candidate) { continue }
                $candidatePid = [int]$candidate.ProcessId
                $candidateKey = "$candidatePid"
                if ($ownedByPid.ContainsKey($candidateKey)) { continue }
                $parentPid = [int]$candidate.ParentProcessId
                $parent = $ownedByPid["$parentPid"]
                if ($null -eq $parent) { continue }
                $currentParent = $snapshotByPid["$parentPid"]
                if ($null -eq $currentParent -or -not (Test-TrackedProcessIdentity -Expected $parent -Current $currentParent)) {
                    continue
                }
                $candidateIdentity = ConvertTo-TrackedProcessIdentity -ProcessInfo $candidate -Depth ([int]$parent.Depth + 1)
                if ($null -eq $candidateIdentity) { continue }
                if ([long]$candidateIdentity.CreationTicks -lt [long]$parent.CreationTicks) {
                    continue
                }
                $boundCandidate = $null
                $accepted = $false
                try {
                    $boundCandidate = Get-Process -Id $candidatePid -ErrorAction Stop
                    $null = $boundCandidate.Handle
                    $candidateStartTicks = $boundCandidate.StartTime.ToUniversalTime().Ticks
                    if (($candidateStartTicks - ($candidateStartTicks % 10)) -ne [long]$candidateIdentity.CreationTicks) {
                        continue
                    }
                    $currentCandidate = Get-CimInstance Win32_Process -Filter "ProcessId=$candidatePid" -ErrorAction SilentlyContinue
                    if (-not (Test-TrackedProcessIdentity -Expected $candidateIdentity -Current $currentCandidate)) {
                        continue
                    }
                    $boundCandidate.Refresh()
                    if ($boundCandidate.HasExited) {
                        continue
                    }
                    $candidateIdentity | Add-Member -NotePropertyName StartTicks -NotePropertyValue ([long]$candidateStartTicks)
                    $candidateIdentity | Add-Member -NotePropertyName BoundProcess -NotePropertyValue $boundCandidate
                    $ownedByPid[$candidateKey] = $candidateIdentity
                    $accepted = $true
                    $added = $true
                } catch {
                    continue
                } finally {
                    if (-not $accepted -and $null -ne $boundCandidate) {
                        try { $boundCandidate.Dispose() } catch { }
                    }
                }
            }
        }
    }
    $stopExactOwnedProcess = {
        param([object]$Expected)
        $candidatePid = [int]$Expected.ProcessId
        $boundProcessProperty = $Expected.PSObject.Properties["BoundProcess"]
        if ($null -eq $boundProcessProperty -or $null -eq $boundProcessProperty.Value) { return $false }
        $boundProcess = $boundProcessProperty.Value
        try {
            $null = $boundProcess.Handle
            $boundTicks = $boundProcess.StartTime.ToUniversalTime().Ticks
            if ($null -eq $Expected.StartTicks -or [long]$Expected.StartTicks -ne [long]$boundTicks) { return $false }
            $current = Get-CimInstance Win32_Process -Filter "ProcessId=$candidatePid" -ErrorAction SilentlyContinue
            if (-not (Test-TrackedProcessIdentity -Expected $Expected -Current $current)) { return $false }
            $boundProcess.Refresh()
            if (-not $boundProcess.HasExited) { $boundProcess.Kill() }
            return $true
        } catch {
            return $false
        }
    }
    $disposeOwnedHandles = {
        foreach ($expected in @($ownedByPid.Values)) {
            if ([int]$expected.Depth -eq 0) { continue }
            $boundProperty = $expected.PSObject.Properties["BoundProcess"]
            if ($null -eq $boundProperty -or $null -eq $boundProperty.Value) { continue }
            try { $boundProperty.Value.Dispose() } catch { $finalizationErrors.Add($_.Exception.Message) }
        }
    }
    $stopRemainingOwnedDescendants = {
        if ($ownedByPid.Count -eq 0) { return }
        $forceWatch = [Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $snapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
            & $registerOwnedLineage $snapshot
            $active = [System.Collections.Generic.List[object]]::new()
            foreach ($processInfo in $snapshot) {
                $candidatePid = [int]$processInfo.ProcessId
                $expected = $ownedByPid["$candidatePid"]
                if (
                    $null -ne $expected -and
                    [int]$expected.Depth -gt 0 -and
                    (Test-TrackedProcessIdentity -Expected $expected -Current $processInfo)
                ) {
                    $active.Add($expected) | Out-Null
                }
            }
            if ($active.Count -eq 0) { return }
            $ordered = @($active | Sort-Object -Property @{ Expression = { [int]$_.Depth }; Descending = $true }, @{ Expression = { [int]$_.ProcessId }; Descending = $true })
            foreach ($expected in $ordered) {
                & $stopExactOwnedProcess $expected | Out-Null
            }
            if ($forceWatch.ElapsedMilliseconds -ge [Math]::Max(0, $ForceTimeoutMs)) { break }
            $remainingBudget = [Math]::Max(0, $ForceTimeoutMs - $forceWatch.ElapsedMilliseconds)
            if ($remainingBudget -gt 0) {
                Start-Sleep -Milliseconds ([Math]::Min(200, $remainingBudget))
            }
        }
        $remainingSnapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        & $registerOwnedLineage $remainingSnapshot
        $remaining = @($remainingSnapshot | Where-Object {
            $expected = $ownedByPid["$([int]$_.ProcessId)"]
            $null -ne $expected -and [int]$expected.Depth -gt 0 -and (Test-TrackedProcessIdentity -Expected $expected -Current $_)
        })
        if ($remaining.Count -gt 0) {
            $remainingPids = @($remaining | ForEach-Object { [int]$_.ProcessId }) -join ","
            throw "Owned descendants for $Component did not exit within $ForceTimeoutMs ms: $remainingPids"
        }
    }
    try {
        $initialSnapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        & $registerOwnedLineage $initialSnapshot
    } catch {
        $finalizationErrors.Add("process lineage snapshot failed: $($_.Exception.Message)")
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $closedMainWindow = $false
            try { $closedMainWindow = $Process.CloseMainWindow() } catch { $closedMainWindow = $false }
            if (-not $closedMainWindow -or -not $Process.WaitForExit($GraceTimeoutMs)) {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    try { $Process.Kill() } catch { }
                }
                if (-not $Process.WaitForExit($ForceTimeoutMs)) {
                    $exitStatus = "shutdown-timeout"
                    throw "Process $Component (PID $($Process.Id)) did not exit after forced shutdown"
                }
            }
        }
        $exitStatus = $Process.ExitCode
    } catch {
        $terminationError = $_.Exception
    } finally {
        try { & $stopRemainingOwnedDescendants } catch { $finalizationErrors.Add($_.Exception.Message) }
        try { & $disposeOwnedHandles } catch { $finalizationErrors.Add($_.Exception.Message) }
        if ($null -ne $Process.VsaLogPump) {
            try { $Process.VsaLogPump.Complete($LogDrainTimeoutMs) } catch { $finalizationErrors.Add($_.Exception.Message) }
        }
        try { Set-ProcessExit -Component $Component -ExitStatus $exitStatus } catch { $finalizationErrors.Add($_.Exception.Message) }
        if ($null -ne $Process.VsaLogPump) {
            try { $Process.VsaLogPump.Dispose() } catch { $finalizationErrors.Add($_.Exception.Message) }
        }
        try { $Process.Dispose() } catch { $finalizationErrors.Add($_.Exception.Message) }
    }
    if ($null -ne $terminationError) {
        if ($finalizationErrors.Count -gt 0) {
            throw "$($terminationError.Message); finalization failed: $($finalizationErrors -join '; ')"
        }
        throw $terminationError
    }
    if ($finalizationErrors.Count -gt 0) {
        throw "Process $Component finalization failed: $($finalizationErrors -join '; ')"
    }
}

function DeleteValidationResources {
    if (-not $Validate) { return }
    $removed = $true
    foreach ($validationResource in @($validationSmokeIndex, $validationIndex)) {
        try {
            $deleteUri = ("$esEndpoint/$validationResource" + "?ignore_unavailable=true")
            Invoke-WebRequest -Uri $deleteUri -Method Delete -TimeoutSec 5 -UseBasicParsing | Out-Null
        } catch {
            Write-Stack "failed to remove validation index $validationResource`: $($_.Exception.Message)" -ErrorLine
            $removed = $false
        }
    }
    foreach ($resource in @(
        @{ Path = $validationDataRoot; Recurse = $true },
        @{ Path = $validationConfigPath; Recurse = $false },
        @{ Path = $configPath; Recurse = $false }
    )) {
        if (-not (Test-Path -LiteralPath $resource.Path)) { continue }
        try {
            Remove-Item -LiteralPath $resource.Path -Force -Recurse:$resource.Recurse -ErrorAction Stop
        } catch {
            Write-Stack "failed to remove validation path $($resource.Path)`: $($_.Exception.Message)" -ErrorLine
            $removed = $false
        }
    }
    if ($removed) { Write-Stack "removed isolated validation namespace $validationIndex" }
    return $removed
}

function Wait-RuntimeProcesses {
    param([hashtable]$Processes, [int]$PollMilliseconds = 250)
    while ($true) {
        $snapshot = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        foreach ($component in $Processes.Keys) {
            $managed = $Processes[$component]
            if ($null -eq $managed) { continue }
            Update-ProcessTracker -Process $managed -Snapshot $snapshot
            $managed.Refresh()
            if ($managed.HasExited) {
                Set-ProcessExit -Component $component -ExitStatus $managed.ExitCode
                throw "$component exited after readiness. ExitCode=$($managed.ExitCode)"
            }
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }
}

try {
    Set-Location $repoRoot
    $sourceConfig = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $repoRoot $Config }
    if (-not (Test-Path -LiteralPath $sourceConfig -PathType Leaf)) {
        throw "source config must be a readable regular file: $sourceConfig"
    }
    Import-PrivateSecretsFile -Path $SecretsFile -Explicit $secretsFileExplicit
    $env:PYTHONPATH = Join-Path $repoRoot "src"

    if ($ProbeProviders) {
        $probe = PythonCommand -CondaEnv $CondaEnv -PythonArgs @("scripts\runtime-doctor.py", "--config", $sourceConfig, "--probe-providers", "--json")
        Write-Stack "running live provider readiness probe"
        & $probe.File @($probe.Args) 2>&1 | ForEach-Object { Write-Stack "$_" }
        $probeStatus = $LASTEXITCODE
        if ($probeStatus -ne 0) {
            Write-Stack "live provider readiness probe failed with exit code $probeStatus" -ErrorLine
            exit $probeStatus
        }
        Write-Stack "live VLM and embedding provider readiness probe succeeded"
        exit 0
    }

    foreach ($port in @($ApiPort, $UiPort)) { Reclaim-Port -Port $port -TimeoutSec $TimeoutSec }

    if ([string]::IsNullOrWhiteSpace($DataRoot)) {
        $DataRoot = Join-Path $repoRoot ".runtime\recorded-video"
    } elseif (-not [System.IO.Path]::IsPathRooted($DataRoot)) {
        $DataRoot = Join-Path $repoRoot $DataRoot
    }
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    Write-SearchConfig -SourceConfig $sourceConfig -TargetConfig $configPath -EsEndpoint $esEndpoint -SelectedIndex $Index -SelectedDataRoot $DataRoot -Mode production
    if ($Validate) {
        Write-SearchConfig -SourceConfig $sourceConfig -TargetConfig $validationConfigPath -EsEndpoint $esEndpoint -SelectedIndex $validationIndex -SelectedDataRoot $validationDataRoot -Mode validation
        $apiConfigPath = $validationConfigPath
    }

    if (-not $SmokeOnly) { Ensure-UiRuntime }

    $doctorArgs = @("scripts\runtime-doctor.py", "--config", $configPath, "--es-endpoint", $esEndpoint, "--phase", "static", "--port", "$ApiPort", "--json")
    if ($SmokeOnly) { $doctorArgs += @("--skip-ui") } else { $doctorArgs += @("--port", "$UiPort") }
    if (-not [string]::IsNullOrWhiteSpace($CondaEnv)) { $doctorArgs += @("--conda-env", $CondaEnv) }
    $doctor = PythonCommand -CondaEnv $CondaEnv -PythonArgs $doctorArgs
    Write-Stack "running static runtime doctor"
    Invoke-StackCommand -FilePath $doctor.File -Arguments $doctor.Args

    $wasRunning = (& docker inspect -f '{{.State.Running}}' vsa-agent-es 2>$null) -eq "true"
    if (-not $wasRunning) { $esStartedByRun = $true }
    & "$PSScriptRoot\es-dev-start.ps1" -Port $EsPort 2>&1 | ForEach-Object { Write-Stack "$_" }
    if ($LASTEXITCODE -ne 0) { throw "Elasticsearch startup failed with exit code $LASTEXITCODE" }
    $esLogProcess = Start-LoggedProcess -Component "es" -FilePath "docker" -Arguments @("compose", "-f", "docker-compose.es.yml", "logs", "-f", "elasticsearch") -WorkingDirectory $repoRoot -LogPath $esLogPath -SafeCommand "docker compose -f docker-compose.es.yml logs -f elasticsearch"

    $doctorArgs = @("scripts\runtime-doctor.py", "--config", $configPath, "--es-endpoint", $esEndpoint, "--phase", "elasticsearch", "--json")
    if (-not [string]::IsNullOrWhiteSpace($CondaEnv)) { $doctorArgs += @("--conda-env", $CondaEnv) }
    $doctor = PythonCommand -CondaEnv $CondaEnv -PythonArgs $doctorArgs
    Write-Stack "validating production alias and mapping without writes"
    Invoke-StackCommand -FilePath $doctor.File -Arguments $doctor.Args

    $env:VSA_CONFIG = $apiConfigPath
    $uvicorn = PythonCommand -CondaEnv $CondaEnv -PythonArgs @("-m", "uvicorn", "vsa_agent.api.routes:app", "--host", "127.0.0.1", "--port", "$ApiPort")
    $apiSafeCommand = if ([string]::IsNullOrWhiteSpace($CondaEnv)) {
        "python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $ApiPort"
    } else {
        "conda run --no-capture-output -n $CondaEnv python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port $ApiPort"
    }
    $apiProcess = Start-LoggedProcess -Component "api" -FilePath $uvicorn.File -Arguments $uvicorn.Args -WorkingDirectory $repoRoot -LogPath $apiLogPath -SafeCommand $apiSafeCommand
    Wait-HttpHealth -Url $apiHealthUrl -TimeoutSec $TimeoutSec -Process $apiProcess

    $worker = PythonCommand -CondaEnv $CondaEnv -PythonArgs @("scripts\recorded-video-worker.py", "--config", $apiConfigPath)
    $workerSafeCommand = if ([string]::IsNullOrWhiteSpace($CondaEnv)) {
        "python scripts/recorded-video-worker.py --config <runtime-config>"
    } else {
        "conda run --no-capture-output -n $CondaEnv python scripts/recorded-video-worker.py --config <runtime-config>"
    }
    $workerProcess = Start-LoggedProcess -Component "worker" -FilePath $worker.File -Arguments $worker.Args -WorkingDirectory $repoRoot -LogPath $workerLogPath -SafeCommand $workerSafeCommand
    Wait-WorkerReady -LogPath $workerLogPath -TimeoutSec $TimeoutSec -Process $workerProcess

    if (-not $SmokeOnly) {
        $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB = "true"
        $env:NEXT_PUBLIC_AGENT_API_URL_BASE = "/api/v1"
        $env:NEXT_PUBLIC_VST_API_URL = "/api/v1/vst"
        $env:VSA_INTERNAL_AGENT_API_URL_BASE = "$apiUrl/api/v1"
        $env:PORT = "$UiPort"
        $uiProcess = Start-LoggedProcess -Component "ui" -FilePath "bash" -Arguments @("scripts/run_original_ui_vss.sh") -WorkingDirectory $repoRoot -LogPath $uiLogPath -SafeCommand "bash scripts/run_original_ui_vss.sh"
        Wait-UiReady -Url $uiUrl -TimeoutSec $TimeoutSec -Process $uiProcess
        Wait-SameOriginProxy -Url $uiUrl -TimeoutSec $TimeoutSec
    }

    if ($Validate) { # validation
        if ($KeepRunning) {
            Write-Stack "READY: isolated validation runtime api=$apiUrl ui=$uiUrl es=$esEndpoint index=$validationIndex"
            Wait-RuntimeProcesses -Processes @{ api = $apiProcess; worker = $workerProcess; ui = $uiProcess }
        } else {
            $smoke = PythonCommand -CondaEnv $CondaEnv -PythonArgs @("scripts\es_ingest_smoke.py", "--api-url", $apiUrl, "--es-endpoint", $esEndpoint, "--index", $validationSmokeIndex, "--video-id", "runtime-validation-$runId", "--insecure")
            Write-Stack "running isolated validation against $validationIndex"
            Invoke-StackCommand -FilePath $smoke.File -Arguments $smoke.Args
            Write-Stack "PASS: ES runtime stack validation succeeded"
        }
    } # validation
    else {
        Write-Stack "PASS: ES recorded-video runtime stack is ready"
        Write-Stack "api=$apiUrl es=$esEndpoint ui=$uiUrl index=$Index data_root=$DataRoot"
        Wait-RuntimeProcesses -Processes @{ api = $apiProcess; worker = $workerProcess; ui = $uiProcess }
    }
} finally {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($managedProcess in @(
        @{ Component = "ui"; Process = $uiProcess },
        @{ Component = "worker"; Process = $workerProcess },
        @{ Component = "api"; Process = $apiProcess },
        @{ Component = "es"; Process = $esLogProcess }
    )) {
        try {
            Stop-OwnedProcessTree -Component $managedProcess.Component -Process $managedProcess.Process
        } catch {
            $cleanupErrors.Add($_.Exception.Message)
        }
    }
    try {
        if ((DeleteValidationResources) -eq $false) { $cleanupErrors.Add("validation cleanup failed") }
    } catch {
        $cleanupErrors.Add($_.Exception.Message)
    }

    $env:VSA_CONFIG = $oldVsaConfig
    $env:PYTHONPATH = $oldPythonPath
    $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB = $oldSearchTab
    $env:NEXT_PUBLIC_AGENT_API_URL_BASE = $oldAgentApiUrl
    $env:NEXT_PUBLIC_VST_API_URL = $oldVstApiUrl
    $env:VSA_INTERNAL_AGENT_API_URL_BASE = $oldInternalAgentApiUrl
    $env:PORT = $oldUiPort
    foreach ($key in @($secretEnvironmentSnapshot.Keys)) {
        $snapshot = $secretEnvironmentSnapshot[$key]
        if ($snapshot.Exists) {
            [Environment]::SetEnvironmentVariable($key, $snapshot.Value, "Process")
        } else {
            [Environment]::SetEnvironmentVariable($key, $null, "Process")
        }
    }

    if ($esStartedByRun -and $StopElasticsearch) {
        try {
            Invoke-StackCommand -FilePath (Join-Path $PSScriptRoot "es-dev-stop.ps1") -Arguments @()
        } catch {
            $cleanupErrors.Add($_.Exception.Message)
        }
    }

    if (-not $Validate -and (Test-Path -LiteralPath $configPath)) {
        Write-Stack "Temporary config retained: $configPath"
    }
    Write-Stack "process manifest: $processManifestPath"
    Write-Stack "stack log: $stackLogPath"
    if ($cleanupErrors.Count -gt 0) {
        throw "Runtime cleanup failed: $($cleanupErrors -join '; ')"
    }
}
