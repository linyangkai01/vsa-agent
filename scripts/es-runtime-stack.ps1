param(
    [int]$ApiPort = 8000,
    [int]$EsPort = 9200,
    [int]$UiPort = 3000,
    [string]$Index = "vsa-video-embeddings",
    [string]$CondaEnv = "",
    [int]$TimeoutSec = 90,
    [switch]$StopElasticsearch,
    [switch]$SmokeOnly
)

$ErrorActionPreference = "Stop"

function Test-PortAvailable {
    param([int]$Port)

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
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
        $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue).CommandLine
        Write-Host "Reclaiming port $Port from PID ${ownerPid}: $command"
        & taskkill.exe /PID $ownerPid /T /F | Out-Null
    }
    Wait-PortFree -Port $Port -TimeoutSec $TimeoutSec
}

function Wait-HttpHealth {
    param(
        [string]$Url,
        [int]$TimeoutSec,
        [System.Diagnostics.Process]$Process
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        if ($Process.HasExited) {
            throw "FastAPI process exited before health check succeeded. ExitCode=$($Process.ExitCode)"
        }

        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 5
            if ($response.status -eq "ok") {
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "FastAPI did not become reachable at $Url within $TimeoutSec seconds"
}

function Write-SearchConfig {
    param(
        [string]$SourceConfig,
        [string]$TargetConfig,
        [string]$EsEndpoint,
        [string]$Index
    )

    $raw = Get-Content -Raw -LiteralPath $SourceConfig
    $searchBlock = @"
search:
  enabled: true
  es_endpoint: $EsEndpoint
  embed_index: $Index
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: true
  force_mock_embedding: true
"@

    $pattern = "(?ms)^search:\r?\n(?:^[ \t]+.*\r?\n?)*"
    if ($raw -match $pattern) {
        $updated = [regex]::Replace($raw, $pattern, $searchBlock + "`r`n", 1)
    } else {
        $updated = $raw.TrimEnd() + "`r`n" + $searchBlock + "`r`n"
    }

    Set-Content -LiteralPath $TargetConfig -Value $updated -Encoding UTF8
}

function PythonCommand {
    param(
        [string]$CondaEnv,
        [string[]]$PythonArgs
    )

    if ([string]::IsNullOrWhiteSpace($CondaEnv)) {
        return @{
            File = "python"
            Args = $PythonArgs
        }
    }

    return @{
        File = "conda"
        Args = @("run", "-n", $CondaEnv, "python") + $PythonArgs
    }
}

function Stop-OwnedProcessTree {
    param([System.Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot ".runtime\es-stack"
$configPath = Join-Path $runtimeDir "config.yaml"
$apiLogPath = Join-Path $runtimeDir "api.log"
$apiErrLogPath = Join-Path $runtimeDir "api.err.log"
$uiLogPath = Join-Path $runtimeDir "ui.log"
$uiErrLogPath = Join-Path $runtimeDir "ui.err.log"
$apiUrl = "http://127.0.0.1:$ApiPort"
$apiHealthUrl = "$apiUrl/health"
$esEndpoint = "http://127.0.0.1:$EsPort"
$apiProcess = $null
$uiProcess = $null
$oldVsaConfig = $env:VSA_CONFIG
$oldPythonPath = $env:PYTHONPATH
$oldSearchTab = $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB
$oldAgentApiUrl = $env:NEXT_PUBLIC_AGENT_API_URL_BASE
$oldUiPort = $env:PORT

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

try {
    Set-Location $repoRoot

    foreach ($port in @($EsPort, $ApiPort, $UiPort)) { Reclaim-Port -Port $port -TimeoutSec $TimeoutSec }

    & "$PSScriptRoot\es-dev-start.ps1" -Port $EsPort
    Write-SearchConfig -SourceConfig (Join-Path $repoRoot "config.yaml") -TargetConfig $configPath -EsEndpoint $esEndpoint -Index $Index

    $env:VSA_CONFIG = $configPath
    $env:PYTHONPATH = Join-Path $repoRoot "src"

    $uvicorn = PythonCommand -CondaEnv $CondaEnv -PythonArgs @(
        "-m", "uvicorn",
        "vsa_agent.api.routes:app",
        "--host", "127.0.0.1",
        "--port", "$ApiPort"
    )

    $apiProcess = Start-Process `
        -FilePath $uvicorn.File `
        -ArgumentList $uvicorn.Args `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $apiLogPath `
        -RedirectStandardError $apiErrLogPath `
        -PassThru

    Wait-HttpHealth -Url $apiHealthUrl -TimeoutSec $TimeoutSec -Process $apiProcess

    $smoke = PythonCommand -CondaEnv $CondaEnv -PythonArgs @(
        "scripts\es_ingest_smoke.py",
        "--api-url", $apiUrl,
        "--es-endpoint", $esEndpoint,
        "--index", $Index,
        "--insecure"
    )

    & $smoke.File @($smoke.Args)
    if ($LASTEXITCODE -ne 0) {
        throw "ES ingest/search smoke failed with exit code $LASTEXITCODE"
    }

    Write-Host "PASS: ES runtime stack validation succeeded"
    Write-Host "  api: $apiUrl"
    Write-Host "  es:  $esEndpoint"
    Write-Host "  index: $Index"
    Write-Host "  config: $configPath"
    if (-not $SmokeOnly) {
        $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB = "true"
        $env:NEXT_PUBLIC_AGENT_API_URL_BASE = "$apiUrl/api/v1"
        $env:PORT = "$UiPort"
        $uiProcess = Start-Process -FilePath "bash" -ArgumentList @("scripts/run_original_ui_vss.sh") -WorkingDirectory $repoRoot -RedirectStandardOutput $uiLogPath -RedirectStandardError $uiErrLogPath -PassThru
        Wait-Process -Id $uiProcess.Id
    }
} finally {
    Stop-OwnedProcessTree -Process $uiProcess
    Stop-OwnedProcessTree -Process $apiProcess

    $env:VSA_CONFIG = $oldVsaConfig
    $env:PYTHONPATH = $oldPythonPath
    $env:NEXT_PUBLIC_ENABLE_SEARCH_TAB = $oldSearchTab
    $env:NEXT_PUBLIC_AGENT_API_URL_BASE = $oldAgentApiUrl
    $env:PORT = $oldUiPort

    if ($StopElasticsearch) {
        & "$PSScriptRoot\es-dev-stop.ps1"
    }

    if (Test-Path -LiteralPath $apiLogPath) {
        Write-Host "API log: $apiLogPath"
    }
    if (Test-Path -LiteralPath $apiErrLogPath) {
        Write-Host "API error log: $apiErrLogPath"
    }
    if (Test-Path -LiteralPath $configPath) {
        Write-Host "Temporary config retained: $configPath"
    }
}
