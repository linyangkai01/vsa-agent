param(
    [string]$Endpoint = "http://127.0.0.1:9200",
    [int]$TimeoutSec = 90
)

$ErrorActionPreference = "Stop"
$deadline = (Get-Date).AddSeconds($TimeoutSec)

do {
    try {
        $response = Invoke-RestMethod -Uri $Endpoint -TimeoutSec 5
        if ($response.cluster_name) {
            Write-Host "PASS: Elasticsearch is reachable at $Endpoint"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "Elasticsearch did not become reachable at $Endpoint within $TimeoutSec seconds"
