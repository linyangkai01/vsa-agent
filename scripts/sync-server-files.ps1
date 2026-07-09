param(
    [string]$TargetRoot = "Z:\vsa-agent",
    [string[]]$IncludePaths = @(
        "scripts\es-runtime-stack.ps1",
        "scripts\es-runtime-stack.sh",
        "scripts\es_ingest_smoke.py",
        "tests\unit\scripts\test_es_runtime_stack_script.py",
        "docs\DEVELOPMENT_STATUS.md",
        "docs\superpowers\reference\es-video-search-runtime.md",
        "docs\superpowers\reports\2026-07-09-script-es-runtime-stack-verification.md",
        "openspec\changes\script-es-runtime-stack\.comet.yaml",
        "openspec\changes\script-es-runtime-stack\proposal.md",
        "openspec\changes\script-es-runtime-stack\design.md",
        "openspec\changes\script-es-runtime-stack\tasks.md",
        "openspec\changes\script-es-runtime-stack\specs\recorded-video-business-flow\spec.md"
    ),
    [switch]$DryRun,
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targetRootCandidate = Join-Path $TargetRoot "."
$targetRootPath = (Resolve-Path -LiteralPath $targetRootCandidate).Path

function Test-TargetWritable {
    param([string]$Path)

    $probePath = Join-Path $Path ".codex-sync-write-test.tmp"
    try {
        [System.IO.File]::WriteAllText($probePath, "ok")
        [System.IO.File]::Delete($probePath)
        return $true
    } catch [System.UnauthorizedAccessException] {
        Write-Error "Access denied while writing to mapped target '$Path'. This script uses the already-authenticated mapped drive and does not request SSH/Git credentials. No password is requested or stored by this script. Run the same command from a normal PowerShell session that owns the Z: mapping, or reconnect the mapping with write access."
        return $false
    } catch {
        Write-Error "Unable to write to mapped target '$Path': $($_.Exception.Message)"
        return $false
    }
}

$missingSources = New-Object System.Collections.Generic.List[string]
foreach ($relativePath in $IncludePaths) {
    $sourcePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        $missingSources.Add($relativePath) | Out-Null
    }
}

if ($missingSources.Count -gt 0) {
    throw "Missing source files:`n  $($missingSources -join "`n  ")"
}

if ($DryRun) {
    Write-Host "DRYRUN: target root $targetRootPath"
} elseif (-not (Test-TargetWritable -Path $targetRootPath)) {
    exit 5
}

if ($PreflightOnly) {
    Write-Host "PASS: mapped target preflight completed"
    Write-Host "  target: $targetRootPath"
    Write-Host "  files:  $($IncludePaths.Count)"
    exit 0
}

$copied = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in $IncludePaths) {
    $sourcePath = Join-Path $repoRoot $relativePath
    $resolvedSource = (Resolve-Path -LiteralPath $sourcePath).Path
    $destinationPath = Join-Path $targetRootPath $relativePath
    $destinationDir = Split-Path -Parent $destinationPath

    if ($DryRun) {
        Write-Host "DRYRUN: $resolvedSource -> $destinationPath"
        continue
    }

    try {
        [System.IO.Directory]::CreateDirectory($destinationDir) | Out-Null
        [System.IO.File]::Copy($resolvedSource, $destinationPath, $true)
    } catch [System.UnauthorizedAccessException] {
        throw "Access denied while writing to mapped target '$destinationPath'. This script uses the already-authenticated mapped drive. No password is requested or stored by this script. Run this command from a normal PowerShell session that owns the Z: mapping: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1"
    }
    $copied.Add($relativePath) | Out-Null
}

if ($DryRun) {
    Write-Host "PASS: dry run completed for selected files"
} else {
    Write-Host "PASS: synced selected files to server target"
    foreach ($item in $copied) {
        Write-Host "  $item"
    }
}
