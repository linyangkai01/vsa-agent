param(
    [int]$ApiPort = 8000,
    [int]$EsPort = 9200,
    [int]$UiPort = 3000,
    [string]$Index = "vsa-video-embeddings",
    [string]$CondaEnv = "",
    [string]$DataRoot = "",
    [int]$TimeoutSec = 90,
    [switch]$StopElasticsearch,
    [switch]$SmokeOnly,
    [switch]$Validate
)

$ErrorActionPreference = "Stop"
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
    if (-not $process.Start()) { throw "Failed to start $Component" }
    try {
        $logPump = [VsaRuntimeLogPump]::new(
            $process.StandardOutput,
            $process.StandardError,
            $LogPath,
            $stackLogPath,
            "[$Component]"
        )
        $process | Add-Member -NotePropertyName VsaLogPump -NotePropertyValue $logPump
    } catch {
        if (-not $process.HasExited) { $process.Kill() }
        $process.Dispose()
        throw
    }
    if ($Record) {
        Add-ManagedProcess -Component $Component -ProcessId $process.Id -SafeCommand $SafeCommand
    }
    return $process
}

function Invoke-StackCommand {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Stack "$_" }
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Assert-CurrentUserProcess {
    param([int]$ProcessId, [object]$ExpectedCreationDate = $null)
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
        Write-Stack "reclaiming port $Port from current-user PID $ownerPid"
        Assert-CurrentUserProcess -ProcessId $ownerPid -ExpectedCreationDate $ownedProcess.CreationDate | Out-Null
        & taskkill.exe /PID $ownerPid /T /F | Out-Null
    }
    Wait-PortFree -Port $Port -TimeoutSec $TimeoutSec
}

function Wait-HttpHealth {
    param([string]$Url, [int]$TimeoutSec, [System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
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
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            & cmd.exe /d /s /c "taskkill.exe /PID $($Process.Id) /T >nul 2>nul"
            if (-not $Process.WaitForExit($GraceTimeoutMs)) {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    & cmd.exe /d /s /c "taskkill.exe /PID $($Process.Id) /T /F >nul 2>nul"
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
    try {
        Invoke-WebRequest -Uri "$esEndpoint/$validationSmokeIndex" -Method Delete -TimeoutSec 5 -UseBasicParsing | Out-Null
    } catch {
        Write-Stack "failed to remove validation index $validationSmokeIndex`: $($_.Exception.Message)" -ErrorLine
        $removed = $false
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
        foreach ($component in $Processes.Keys) {
            $managed = $Processes[$component]
            if ($null -eq $managed) { continue }
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
    foreach ($port in @($ApiPort, $UiPort)) { Reclaim-Port -Port $port -TimeoutSec $TimeoutSec }

    if ([string]::IsNullOrWhiteSpace($DataRoot)) {
        $DataRoot = Join-Path $repoRoot ".runtime\recorded-video"
    } elseif (-not [System.IO.Path]::IsPathRooted($DataRoot)) {
        $DataRoot = Join-Path $repoRoot $DataRoot
    }
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    Write-SearchConfig -SourceConfig (Join-Path $repoRoot "config.yaml") -TargetConfig $configPath -EsEndpoint $esEndpoint -SelectedIndex $Index -SelectedDataRoot $DataRoot -Mode production
    if ($Validate) {
        Write-SearchConfig -SourceConfig (Join-Path $repoRoot "config.yaml") -TargetConfig $validationConfigPath -EsEndpoint $esEndpoint -SelectedIndex $validationIndex -SelectedDataRoot $validationDataRoot -Mode validation
        $apiConfigPath = $validationConfigPath
    }

    $env:PYTHONPATH = Join-Path $repoRoot "src"
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
        $smoke = PythonCommand -CondaEnv $CondaEnv -PythonArgs @("scripts\es_ingest_smoke.py", "--api-url", $apiUrl, "--es-endpoint", $esEndpoint, "--index", $validationSmokeIndex, "--video-id", "runtime-validation-$runId", "--insecure")
        Write-Stack "running isolated validation against $validationIndex"
        Invoke-StackCommand -FilePath $smoke.File -Arguments $smoke.Args
        Write-Stack "PASS: ES runtime stack validation succeeded"
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
