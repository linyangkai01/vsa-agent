param(
    [int]$ApiPort = 8000,
    [int]$EsPort = 9200,
    [string]$Index = "vsa-video-embeddings",
    [string]$CondaEnv = "",
    [int]$TimeoutSec = 90,
    [switch]$StopElasticsearch
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

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot ".runtime\es-stack"
$configPath = Join-Path $runtimeDir "config.yaml"
$apiLogPath = Join-Path $runtimeDir "api.log"
$apiErrLogPath = Join-Path $runtimeDir "api.err.log"
$apiUrl = "http://127.0.0.1:$ApiPort"
$apiHealthUrl = "$apiUrl/health"
$esEndpoint = "http://127.0.0.1:$EsPort"
$apiProcess = $null
$oldVsaConfig = $env:VSA_CONFIG
$oldPythonPath = $env:PYTHONPATH

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

try {
    Set-Location $repoRoot

    if (-not (Test-PortAvailable -Port $ApiPort)) {
        throw "API port $ApiPort is already in use. Pass -ApiPort with another value."
    }

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
} finally {
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force
    }

    $env:VSA_CONFIG = $oldVsaConfig
    $env:PYTHONPATH = $oldPythonPath

    if ($StopElasticsearch) {
        & "$PSScriptRoot\es-dev-stop.ps1"
    }

    if (Test-Path -LiteralPath $apiLogPath) {
        Write-Host "API log: $apiLogPath"
    }
    if (Test-Path -LiteralPath $apiErrLogPath) {
        Write-Host "API error log: $apiErrLogPath"
    }
}
