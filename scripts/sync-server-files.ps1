param(
    [string]$TargetRoot = "Z:\vsa-agent",
    [string[]]$IncludePaths = @(
        "docker-compose.es.yml",
        "pyproject.toml",
        "environment.yml",
        "scripts\es-runtime-stack.ps1",
        "scripts\es-runtime-stack.sh",
        "scripts\bootstrap_node.sh",
        "scripts\run_original_ui_vss.sh",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\next.config.js",
        "scripts\es_ingest_smoke.py",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\utils\data\throttle.ts",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\__tests__\utils\throttle.test.ts",
        "src\vsa_agent\config.py",
        "src\vsa_agent\api\routes.py",
        "src\vsa_agent\api\video_search_ingest.py",
        "src\vsa_agent\api\original_ui_search.py",
        "src\vsa_agent\agents\search_agent.py",
        "src\vsa_agent\tools\embed_search.py",
        "tests\unit\scripts\test_es_runtime_stack_script.py",
        "tests\unit\scripts\test_es_ingest_smoke.py",
        "tests\unit\api\test_original_ui_search_route.py",
        "tests\unit\test_config_search.py",
        "tests\unit\tools\test_embed_search.py",
        "docs\DEVELOPMENT_STATUS.md",
        "docs\superpowers\reference\es-video-search-runtime.md",
        "docs\superpowers\reports\2026-07-09-script-es-runtime-stack-verification.md",
        "docs\superpowers\plans\2026-07-11-interactive-es-ui-validation.md",
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

$repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$targetRootCandidate = Join-Path $TargetRoot "."
$targetRootPath = (Resolve-Path -LiteralPath $targetRootCandidate).Path

function Resolve-PathWithinRoot {
    param(
        [string]$Root,
        [string]$RelativePath,
        [string]$Label
    )

    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "Path '$RelativePath' escapes $Label root."
    }

    $normalizedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $candidatePath = [System.IO.Path]::GetFullPath((Join-Path $normalizedRoot $RelativePath))
    $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidatePath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$RelativePath' escapes $Label root."
    }

    return $candidatePath
}

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
    $sourcePath = Resolve-PathWithinRoot -Root $repoRoot -RelativePath $relativePath -Label "repository"
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
    $sourcePath = Resolve-PathWithinRoot -Root $repoRoot -RelativePath $relativePath -Label "repository"
    $resolvedSource = (Resolve-Path -LiteralPath $sourcePath).Path
    $destinationPath = Resolve-PathWithinRoot -Root $targetRootPath -RelativePath $relativePath -Label "target"
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
