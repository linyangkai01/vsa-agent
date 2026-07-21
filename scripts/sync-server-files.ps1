param(
    [string]$TargetRoot = "Z:\vsa-agent",
    [string[]]$IncludePaths,
    [switch]$DryRun,
    [switch]$PreflightOnly
)

$ApprovedPaths = @(
        "config.yaml",
        "docker-compose.es.yml",
        "pyproject.toml",
        "environment.yml",
        "scripts\bootstrap_node.sh",
        "scripts\es-runtime-stack.ps1",
        "scripts\es-runtime-stack.sh",
        "scripts\es_ingest_smoke.py",
        "scripts\lib\RuntimeLogPump.cs",
        "scripts\recorded-video-production-acceptance.py",
        "scripts\recorded-video-validate.py",
        "scripts\recorded-video-worker.py",
        "scripts\run_original_ui_vss.sh",
        "scripts\runtime-doctor.py",
        "scripts\runtime-log-supervisor.py",
        "src\vsa_agent\config.py",
        "src\vsa_agent\prompt.py",
        "src\vsa_agent\agents\search_agent.py",
        "src\vsa_agent\api\original_ui_chat.py",
        "src\vsa_agent\api\original_ui_search.py",
        "src\vsa_agent\api\recorded_video.py",
        "src\vsa_agent\api\recorded_video_vst.py",
        "src\vsa_agent\api\routes.py",
        "src\vsa_agent\api\video_search_ingest.py",
        "src\vsa_agent\tools\embed_search.py",
        "src\vsa_agent\tools\search.py",
        "src\vsa_agent\tools\search_pipeline.py",
        "src\vsa_agent\recorded_video\assets.py",
        "src\vsa_agent\recorded_video\composition.py",
        "src\vsa_agent\recorded_video\errors.py",
        "src\vsa_agent\recorded_video\es_index.py",
        "src\vsa_agent\recorded_video\media.py",
        "src\vsa_agent\recorded_video\models.py",
        "src\vsa_agent\recorded_video\pipeline.py",
        "src\vsa_agent\recorded_video\ports.py",
        "src\vsa_agent\recorded_video\production_acceptance.py",
        "src\vsa_agent\recorded_video\production_evidence.py",
        "src\vsa_agent\recorded_video\production_runner.py",
        "src\vsa_agent\recorded_video\providers.py",
        "src\vsa_agent\recorded_video\repository.py",
        "src\vsa_agent\recorded_video\segmenter.py",
        "src\vsa_agent\recorded_video\worker.py",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\package.json",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\next.config.js",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\playwright.config.ts",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\e2e\config.e2e.yaml",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\e2e\fake-openai-provider.py",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\e2e\fixtures.ts",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\e2e\recorded-video.spec.ts",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\pages\api\v1\[...path].ts",
        "frontend\original-ui\apps\nv-metropolis-bp-vss-ui\__tests__\api\proxy.test.ts",
        "frontend\original-ui\packages\common\lib-src\index.ts",
        "frontend\original-ui\packages\common\lib-src\utils\recordedVideoJob.ts",
        "frontend\original-ui\packages\common\lib-src\utils\videoModal.ts",
        "frontend\original-ui\packages\common\lib-src\utils\videoUpload.ts",
        "frontend\original-ui\packages\common\__tests__\utils\jobStatus.test.ts",
        "frontend\original-ui\packages\common\__tests__\utils\videoModal.test.ts",
        "frontend\original-ui\packages\common\__tests__\utils\videoUpload.test.ts",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\components\Chat\ChatFileUpload.tsx",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\lib-src\index.d.ts",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\lib-src\index.ts",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\jest.config.js",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\__tests__\components\ChatFileUpload.jobs.test.tsx",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\utils\data\throttle.ts",
        "frontend\original-ui\packages\nemo-agent-toolkit-ui\__tests__\utils\throttle.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\VideoManagementComponent.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\api.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\chunkedUpload.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\components\UploadProgressPanel.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\types.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\lib-src\videoDelete.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\__tests__\chunkedUpload.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\__tests__\components\UploadProgressPanel.test.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\__tests__\components\VideoManagementComponent.jobs.test.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\__tests__\utils\vstFacade.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\video-management\__tests__\videoDelete.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\lib-src\types.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\lib-src\hooks\useSearch.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\lib-src\components\VideoSearchList.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\lib-src\utils\agentResponseParser.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\__tests__\hooks\useSearch.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\__tests__\components\VideoSearchList.test.tsx",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\search\__tests__\utils\agentResponseParser.test.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\map\lib-src\server.d.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\dashboard\lib-src\server.d.ts",
        "frontend\original-ui\packages\nv-metropolis-bp-vss-ui\alerts\lib-src\server.d.ts",
        "tests\integration\conftest.py",
        "tests\integration\test_recorded_video_flow.py",
        "tests\unit\api\test_original_ui_chat.py",
        "tests\unit\api\test_original_ui_search_route.py",
        "tests\unit\api\test_recorded_video_delete.py",
        "tests\unit\api\test_recorded_video_jobs.py",
        "tests\unit\api\test_recorded_video_media.py",
        "tests\unit\api\test_recorded_video_upload.py",
        "tests\unit\api\test_recorded_video_vst.py",
        "tests\unit\recorded_video\__init__.py",
        "tests\unit\recorded_video\test_assets.py",
        "tests\unit\recorded_video\test_composition.py",
        "tests\unit\recorded_video\test_config.py",
        "tests\unit\recorded_video\test_es_index.py",
        "tests\unit\recorded_video\test_es_projection.py",
        "tests\unit\recorded_video\test_media.py",
        "tests\unit\recorded_video\test_models.py",
        "tests\unit\recorded_video\test_pipeline.py",
        "tests\unit\recorded_video\test_ports.py",
        "tests\unit\recorded_video\test_production_acceptance.py",
        "tests\unit\recorded_video\test_production_evidence.py",
        "tests\unit\recorded_video\test_providers.py",
        "tests\unit\recorded_video\test_repository.py",
        "tests\unit\recorded_video\test_segmenter.py",
        "tests\unit\recorded_video\test_worker.py",
        "tests\unit\recorded_video\test_worker_recovery.py",
        "tests\unit\scripts\test_es_ingest_smoke.py",
        "tests\unit\scripts\test_es_runtime_stack_script.py",
        "tests\unit\scripts\test_recorded_video_runtime_launcher.py",
        "tests\unit\scripts\test_recorded_video_validate.py",
        "tests\unit\scripts\test_runtime_doctor.py",
        "tests\unit\api\test_video_search_ingest.py",
        "tests\unit\test_config_search.py",
        "tests\unit\test_prompt.py",
        "tests\unit\tools\test_embed_search.py",
        "tests\acceptance\test_recorded_video_validation_report.py",
        "docs\DEVELOPMENT_STATUS.md",
        "docs\recorded-video-runtime.md",
        "docs\es-video-search-runtime.md",
        "docs\recorded-video-validation.md"
)

$ErrorActionPreference = "Stop"

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

function Test-ForbiddenSyncPath {
    param([string]$RelativePath)

    $portablePath = $RelativePath.Trim().Replace("\", "/")
    return (
        $portablePath -match '(^|/)\.runtime(/|$)' -or
        $portablePath -match '(^|/)\.env([./]|$)' -or
        $portablePath -match '(^|/)(secrets?|credentials?)([./_-]|$)'
    )
}

$approvedPathSet = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($approvedPath in $ApprovedPaths) {
    $approvedPathSet.Add($approvedPath) | Out-Null
}

$SelectedPaths = New-Object System.Collections.Generic.List[string]
$requestedPaths = if ($PSBoundParameters.ContainsKey("IncludePaths")) { @($IncludePaths) } else { @($ApprovedPaths) }
foreach ($relativePath in $requestedPaths) {
    if (Test-ForbiddenSyncPath -RelativePath $relativePath) {
        throw "Path '$relativePath' is forbidden for server sync. Runtime and secret paths are never approved."
    }
    $normalizedPath = $relativePath.Trim().Replace("/", "\")
    if (-not $approvedPathSet.Contains($normalizedPath)) {
        throw "Path '$relativePath' is not approved for server sync. IncludePaths may only select ApprovedPaths entries."
    }
    $SelectedPaths.Add($normalizedPath) | Out-Null
}

$repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$targetRootCandidate = Join-Path $TargetRoot "."
$targetRootPath = (Resolve-Path -LiteralPath $targetRootCandidate).Path

$missingSources = New-Object System.Collections.Generic.List[string]
foreach ($relativePath in $SelectedPaths) {
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
    Write-Host "  files:  $($SelectedPaths.Count)"
    exit 0
}

$copied = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in $SelectedPaths) {
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
