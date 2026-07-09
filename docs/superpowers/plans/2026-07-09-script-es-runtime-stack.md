---
change: script-es-runtime-stack
design-doc: docs/superpowers/specs/2026-07-06-script-es-runtime-stack-design.md
base-ref: 63346ee54bf32c7593fde8deecb23d86712902cf
---

# Script ES Runtime Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one repeatable PowerShell command that starts Elasticsearch, starts FastAPI with a temporary search-enabled config, runs ES ingest/search smoke validation, and cleans up owned resources.

**Architecture:** Keep service lifecycle orchestration in PowerShell because the existing ES lifecycle scripts are PowerShell and the server sync target is a Windows mapped drive. Keep `scripts/es_ingest_smoke.py` focused on API/Elasticsearch assertions. Add offline tests that inspect generated scripts and docs without starting Docker or FastAPI.

**Tech Stack:** PowerShell 5+, Docker Compose through existing ES scripts, Python/Uvicorn for `vsa_agent.api.routes:app`, pytest for offline script/docs validation, OpenSpec/Comet for lifecycle tracking.

## Global Constraints

- Development must follow Comet and this plan belongs to OpenSpec change `script-es-runtime-stack`.
- Keep committed `config.yaml` with `search.enabled: false`.
- Do not implement original NVIDIA VSS Kafka, Logstash, VST, or MDX services.
- Do not store video bytes in Elasticsearch.
- Do not require Docker or Elasticsearch for normal unit tests.
- Sync changed scripts, docs, tests, and OpenSpec files to `Z:\vsa-agent` after local implementation when sandbox access allows it.
- Finish work on the local development branch, merge locally to `master`, and push only remote `master`.

---

## File Structure

- Create `scripts/es-runtime-stack.ps1`: stack-level orchestrator. It starts ES, writes temporary config, starts FastAPI, waits for health, invokes `scripts/es_ingest_smoke.py`, and cleans up.
- Create `tests/unit/scripts/test_es_runtime_stack_script.py`: offline static tests for the PowerShell script. These tests verify expected parameters, referenced lifecycle scripts, temporary config path, smoke command, cleanup behavior, and PASS output strings without running PowerShell services.
- Modify `docs/superpowers/reference/es-video-search-runtime.md`: add one-command local and mapped-server usage, expected output, cleanup, and troubleshooting.
- Modify `docs/DEVELOPMENT_STATUS.md`: record that `script-es-runtime-stack` is active and identify the next validation command.
- Modify `openspec/changes/script-es-runtime-stack/tasks.md`: check off tasks as they are completed and record any blocked runtime validation.
- Modify `openspec/changes/script-es-runtime-stack/.comet.yaml`: record plan path, build mode selections, and later verification metadata.

## Task 1: Add Offline Contract Tests For The Stack Script

**Files:**
- Create: `tests/unit/scripts/test_es_runtime_stack_script.py`
- Verify against: `scripts/es-runtime-stack.ps1`

**Interfaces:**
- Consumes: planned script path `scripts/es-runtime-stack.ps1`
- Produces: offline tests that define expected script contract before implementation

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/scripts/test_es_runtime_stack_script.py` with:

```python
from pathlib import Path


SCRIPT = Path("scripts/es-runtime-stack.ps1")


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_es_runtime_stack_script_exists():
    assert SCRIPT.exists()


def test_es_runtime_stack_exposes_expected_parameters():
    text = _script_text()

    for parameter in (
        "[int]$ApiPort = 8000",
        "[int]$EsPort = 9200",
        '[string]$Index = "vsa-video-embeddings"',
        '[string]$CondaEnv = ""',
        "[switch]$StopElasticsearch",
    ):
        assert parameter in text


def test_es_runtime_stack_uses_existing_lifecycle_and_smoke_scripts():
    text = _script_text()

    assert "es-dev-start.ps1" in text
    assert "es-dev-stop.ps1" in text
    assert "es_ingest_smoke.py" in text
    assert "vsa_agent.api.routes:app" in text
    assert "Invoke-RestMethod" in text


def test_es_runtime_stack_generates_temporary_search_config():
    text = _script_text()

    assert ".runtime" in text
    assert "es-stack" in text
    assert "VSA_CONFIG" in text
    assert "search:" in text
    assert "enabled: true" in text
    assert "verify_certs: false" in text
    assert "config.yaml" in text


def test_es_runtime_stack_reports_pass_and_cleans_up_owned_process():
    text = _script_text()

    assert "PASS: ES runtime stack validation succeeded" in text
    assert "Stop-Process" in text
    assert "$apiProcess" in text
    assert "finally" in text
```

- [ ] **Step 2: Run the new test and confirm red**

Run:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py -q
```

Expected: FAIL because `scripts/es-runtime-stack.ps1` does not exist.

- [ ] **Step 3: Commit the failing contract test**

Run:

```powershell
git add tests/unit/scripts/test_es_runtime_stack_script.py
git commit -m "test: define es runtime stack script contract"
```

## Task 2: Implement The PowerShell Stack Orchestrator

**Files:**
- Create: `scripts/es-runtime-stack.ps1`
- Test: `tests/unit/scripts/test_es_runtime_stack_script.py`

**Interfaces:**
- Consumes: existing `scripts/es-dev-start.ps1`, `scripts/es-dev-stop.ps1`, `scripts/es_ingest_smoke.py`
- Produces: `scripts/es-runtime-stack.ps1` with parameters `ApiPort`, `EsPort`, `Index`, `CondaEnv`, `TimeoutSec`, `StopElasticsearch`

- [ ] **Step 1: Create the stack script**

Create `scripts/es-runtime-stack.ps1`:

```powershell
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
        if ($listener -ne $null) {
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
$apiUrl = "http://127.0.0.1:$ApiPort"
$apiHealthUrl = "$apiUrl/health"
$esEndpoint = "http://127.0.0.1:$EsPort"
$apiProcess = $null

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

try {
    Set-Location $repoRoot

    if (-not (Test-PortAvailable -Port $ApiPort)) {
        throw "API port $ApiPort is already in use. Pass -ApiPort with another value."
    }

    & "$PSScriptRoot\es-dev-start.ps1" -Port $EsPort
    Write-SearchConfig -SourceConfig (Join-Path $repoRoot "config.yaml") -TargetConfig $configPath -EsEndpoint $esEndpoint -Index $Index

    $uvicorn = PythonCommand -CondaEnv $CondaEnv -PythonArgs @(
        "-m", "uvicorn",
        "vsa_agent.api.routes:app",
        "--host", "127.0.0.1",
        "--port", "$ApiPort"
    )

    $envBlock = @{
        VSA_CONFIG = $configPath
        PYTHONPATH = Join-Path $repoRoot "src"
    }

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $uvicorn.File
    foreach ($arg in $uvicorn.Args) {
        [void]$startInfo.ArgumentList.Add($arg)
    }
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    foreach ($key in $envBlock.Keys) {
        $startInfo.Environment[$key] = $envBlock[$key]
    }

    $apiProcess = [System.Diagnostics.Process]::Start($startInfo)
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
    if ($apiProcess -ne $null -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force
    }
    if ($StopElasticsearch) {
        & "$PSScriptRoot\es-dev-stop.ps1"
    }
    if (Test-Path -LiteralPath $apiLogPath) {
        Write-Host "API log: $apiLogPath"
    }
}
```

- [ ] **Step 2: Run focused script contract tests**

Run:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py -q
```

Expected: PASS.

- [ ] **Step 3: Check PowerShell syntax**

Run:

```powershell
powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw scripts\es-runtime-stack.ps1)); 'PASS'"
```

Expected: prints `PASS`.

- [ ] **Step 4: Commit script implementation**

Run:

```powershell
git add scripts/es-runtime-stack.ps1 tests/unit/scripts/test_es_runtime_stack_script.py
git commit -m "feat: add es runtime stack script"
```

## Task 3: Update Runtime Documentation And Active Status

**Files:**
- Modify: `docs/superpowers/reference/es-video-search-runtime.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `openspec/changes/script-es-runtime-stack/tasks.md`

**Interfaces:**
- Consumes: `scripts/es-runtime-stack.ps1`
- Produces: documented one-command local and mapped-server runtime validation workflow

- [ ] **Step 1: Update runtime reference documentation**

In `docs/superpowers/reference/es-video-search-runtime.md`, add a section after "Ingest And Search Validation":

```markdown
## One-Command Stack Validation

Use this when you want the project to start Elasticsearch, start FastAPI with a temporary search-enabled config, and run ingest/search smoke validation:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200 -Index vsa-video-embeddings
```

Expected success output includes:

```text
PASS: ES runtime stack validation succeeded
  api: http://127.0.0.1:8000
  es:  http://127.0.0.1:9200
  index: vsa-video-embeddings
```

The script writes a temporary config under `.runtime\es-stack\config.yaml` and passes it to the API process through `VSA_CONFIG`. The committed `config.yaml` remains unchanged and keeps `search.enabled: false`.

To stop Elasticsearch after validation, include:

```powershell
.\scripts\es-runtime-stack.ps1 -StopElasticsearch
```

If the script reports Docker, port, Uvicorn, or smoke validation failures, treat that output as the runtime blocker and do not report ES runtime validation as successful.
```

Also update the mapped server section:

```markdown
From the mapped server copy:

```powershell
cd Z:\vsa-agent
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

`Z:\vsa-agent` must be executable from the current Windows session and Docker/Python must be available in that execution environment. File mapping alone is not proof that commands are running on the remote server.
```

- [ ] **Step 2: Update development status**

In `docs/DEVELOPMENT_STATUS.md`, add or update a concise active-work note:

```markdown
## Active Change

- `script-es-runtime-stack`: building a PowerShell stack command that starts ES, starts FastAPI with a temporary search-enabled config, runs ingest/search smoke validation, and cleans up owned resources.
- Next validation command: `.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200`.
```

If the file already has an Active Change section, replace only that section. Do not rewrite unrelated historical status.

- [ ] **Step 3: Check off completed OpenSpec tasks for design and docs progress**

In `openspec/changes/script-es-runtime-stack/tasks.md`, check:

```markdown
- [x] 1.1 Confirm the stack wrapper boundaries around existing ES lifecycle scripts, FastAPI startup, temporary config, smoke validation, and cleanup.
- [x] 1.2 Identify the minimal testable units for stack behavior without requiring Docker or a live API in normal unit tests.
- [x] 3.1 Update ES runtime documentation with one-command local validation, mapped-server `Z:\vsa-agent` usage, expected output, and troubleshooting.
- [x] 3.2 Update development status or verification notes so the project state clearly shows this change is in progress.
```

- [ ] **Step 4: Run documentation/static checks**

Run:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
npx openspec validate script-es-runtime-stack
```

Expected: pytest passes and OpenSpec reports `Change 'script-es-runtime-stack' is valid`.

- [ ] **Step 5: Commit docs and task updates**

Run:

```powershell
git add docs/superpowers/reference/es-video-search-runtime.md docs/DEVELOPMENT_STATUS.md openspec/changes/script-es-runtime-stack/tasks.md
git commit -m "docs: document es runtime stack validation"
```

## Task 4: Runtime Attempt, Server Sync, And Build Closeout

**Files:**
- Modify: `openspec/changes/script-es-runtime-stack/.comet.yaml`
- Modify: `openspec/changes/script-es-runtime-stack/tasks.md`
- Create or modify if needed: `docs/superpowers/reports/2026-07-09-script-es-runtime-stack-verification.md`
- Sync target: `Z:\vsa-agent`

**Interfaces:**
- Consumes: completed stack script and docs
- Produces: verification evidence and synced server copy

- [ ] **Step 1: Run focused local verification**

Run:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
npx openspec validate script-es-runtime-stack
powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw scripts\es-runtime-stack.ps1)); 'PASS'"
```

Expected: all tests pass, OpenSpec validates, PowerShell parse prints `PASS`.

- [ ] **Step 2: Attempt full runtime validation when Docker is available**

Run:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

Expected when Docker/Python runtime is available:

```text
PASS: ES runtime stack validation succeeded
```

If Docker is unavailable, the command should fail with a clear blocker. Record the blocker exactly and continue; do not claim runtime validation succeeded.

- [ ] **Step 3: Write verification report**

Create `docs/superpowers/reports/2026-07-09-script-es-runtime-stack-verification.md` with:

```markdown
# script-es-runtime-stack Verification

## Summary

- Change: `script-es-runtime-stack`
- Result: PASS for offline/unit/OpenSpec validation.
- Runtime stack validation: <PASS or BLOCKED with exact blocker>.

## Commands

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
npx openspec validate script-es-runtime-stack
powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw scripts\es-runtime-stack.ps1)); 'PASS'"
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

## Server Sync

Synced changed files to `Z:\vsa-agent` when sandbox permissions allowed it.
```

Replace placeholders with real evidence from the commands.

- [ ] **Step 4: Sync changed files to `Z:\vsa-agent`**

Run after local commits:

```powershell
robocopy D:\WorkPlace\vsa-agent\scripts Z:\vsa-agent\scripts es-runtime-stack.ps1
robocopy D:\WorkPlace\vsa-agent\tests\unit\scripts Z:\vsa-agent\tests\unit\scripts test_es_runtime_stack_script.py
robocopy D:\WorkPlace\vsa-agent\docs Z:\vsa-agent\docs /E
robocopy D:\WorkPlace\vsa-agent\openspec Z:\vsa-agent\openspec /E
```

Treat robocopy exit codes `0` through `7` as success and `8` or above as failure.

- [ ] **Step 5: Check off remaining OpenSpec tasks**

Update `openspec/changes/script-es-runtime-stack/tasks.md` so completed tasks are checked. If runtime validation is blocked by Docker or server execution environment, leave the runtime-attempt task checked only if the attempt was made and the blocker was recorded in the verification report.

- [ ] **Step 6: Commit verification and closeout updates**

Run:

```powershell
git add openspec/changes/script-es-runtime-stack/.comet.yaml openspec/changes/script-es-runtime-stack/tasks.md docs/superpowers/reports/2026-07-09-script-es-runtime-stack-verification.md
git commit -m "chore: verify es runtime stack validation"
```

## Self-Review

- Spec coverage: Task 2 covers stack startup, temporary config, API health, smoke invocation, PASS output, and cleanup. Task 3 covers local and mapped-server documentation. Task 4 covers verification, blocker recording, and server sync.
- Placeholder scan: no TBD/TODO/later placeholders are left in task instructions.
- Type consistency: file paths and script parameters match the design doc: `ApiPort`, `EsPort`, `Index`, `CondaEnv`, `StopElasticsearch`, and `TimeoutSec`.
