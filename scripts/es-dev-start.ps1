param(
    [int]$Port = 9200,
    [string]$DataDir = ".runtime\elasticsearch",
    [string]$ContainerName = "vsa-agent-es"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$env:VSA_ES_PORT = "$Port"
$env:VSA_ES_DATA_DIR = $DataDir
$env:VSA_ES_CONTAINER_NAME = $ContainerName

docker compose -f docker-compose.es.yml up -d
& "$PSScriptRoot\es-dev-probe.ps1" -Endpoint "http://127.0.0.1:$Port"
