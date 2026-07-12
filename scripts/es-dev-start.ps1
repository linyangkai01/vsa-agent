param(
    [int]$Port = 9200,
    [string]$ContainerName = "vsa-agent-es"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$env:VSA_ES_PORT = "$Port"
$env:VSA_ES_CONTAINER_NAME = $ContainerName

docker compose -f docker-compose.es.yml up -d
& "$PSScriptRoot\es-dev-probe.ps1" -Endpoint "http://127.0.0.1:$Port"
