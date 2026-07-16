# Task 22 Launcher Report

Status: DONE

## Scope

- Added explicit isolated keep-running validation mode to the Bash and PowerShell launchers.
- Preserved plain validation smoke behavior and production mode.
- Added behavioral coverage for option rejection, readiness, smoke omission, long-running monitoring, component failure, signal/finally cleanup, and isolated index/data/config removal.
- Did not edit Task 23 validator/sync files or project `.runtime` data.

## TDD / Recovery Evidence

The recovery started with both test-first and production partial diffs already present from the failed upstream implementer. No missing-feature RED was recreated or claimed.

Observed recovery failures before further edits:

```text
pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py -q
RESULT: outer timeout after 124 seconds, no completed result

pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py::test_bash_keep_running_reaches_readiness_stays_alive_and_cleans_on_signal -vv -s
RESULT: FAIL after about 17 seconds; fixed 10-second harness readiness window expired while launcher remained alive

pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py::test_powershell_keep_running_reaches_readiness_stays_alive_and_cleans_on_interrupt -vv -s
RESULT: outer timeout; launcher stdout showed CTRL_BREAK_EVENT entered Windows PowerShell debug mode at Wait-RuntimeProcesses instead of terminating
```

Root-cause evidence came from the generated stack/trace logs: both launchers reached the isolated READY line, skipped the smoke, and reached same-origin proxy readiness. The failures were in the Windows test interruption mechanism and fixed total observation window. The Bash test now sends TERM to the MSYS PID from Git Bash. The PowerShell test triggers a monitored fake API exit after READY so the launcher executes its normal `finally` path.

Final focused evidence:

```text
test_bash_keep_running_reaches_readiness_stays_alive_and_cleans_on_signal
1 passed in 22.53s

test_powershell_keep_running_reaches_readiness_stays_alive_and_cleans_on_component_exit
1 passed in 19.53s
```

## Final Verification

```text
pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py -q
87 passed in 289.68s

ruff check tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py
All checks passed!

ruff format --check tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py
2 files already formatted

bash -n scripts/es-runtime-stack.sh
PASS

PowerShell Language.Parser.ParseFile scripts/es-runtime-stack.ps1
PowerShell parser: OK

git diff --check
PASS

launcher harness residual process check
none
```

## Commit

Implementation commit: `cb82ae7`

## Risk Signals

- Windows PowerShell maps `CTRL_BREAK_EVENT` to debugger entry in this noninteractive harness. PowerShell coverage therefore proves API/Worker/UI monitoring and cleanup through a nonzero component exit and normal `finally`, not direct console-host interruption.
- Git Bash process startup under sustained Windows test load is slow; the behavioral test uses a 30-second outer observation window while preserving the launcher's three-second per-readiness-stage test timeout and bounded shutdown settings.

## Review Repair Round 1

Implementation commit: `1a3dd88ce144b6d92dde4fb30a56414086efa167`

The repair changed only `tests/unit/scripts/test_recorded_video_runtime_launcher.py`. No launcher source defect was found. The PowerShell launcher already owns API, Worker, UI, and ES log-process cleanup in its top-level `finally`; the defect was the test helper's unguarded `Popen` lifecycle.

### Root Cause and RED

`_run_powershell_runtime` could leave its PowerShell host and descendants alive when marker reads, polling, assertions, or `wait()` raised. Its timeout branch killed only the host and did not establish descendant ownership.

Before the RED run, a CIM scan found no process whose command line or lineage identified a launcher harness temporary repository. Unrelated historical `Robocopy.exe` processes containing the launcher filename were not touched.

```text
pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py::test_powershell_helper_abandoned_wait_reclaims_only_its_owned_process_tree tests/unit/scripts/test_recorded_video_runtime_launcher.py::test_powershell_external_pipeline_stop_runs_launcher_finally_and_cleans_owned_runtime -q
RESULT: 2 failed in 1.77s

- Intentional wait abandonment left PID 22176 alive with a command line rooted at the unique pytest temporary powershell-runtime-repo.
- The external interruption test failed because the helper did not yet support stop_pipeline_after_trace.
- The RED test's emergency cleanup rechecked PID plus CreationDate before terminating the exact temporary-repo-owned process; the follow-up residual scan was empty.
```

### Repair and GREEN

- Every PowerShell harness invocation now uses one `Popen` path guarded by `try/finally`.
- A start gate lets the helper capture the host PID and CIM CreationDate before the launcher can exit.
- Cleanup first writes the fake API's monitored-exit trigger and waits for the launcher's own `finally`.
- Only if graceful cleanup fails does the helper select processes from the unique temporary repo command line plus parent lineage, recheck PID and CreationDate, terminate deepest descendants first, and write `harness=forced-cleanup` to the trace.
- Assertion failures retain trace, stdout, stderr, and stack-log diagnostics.
- Windows PowerShell 5.1 host-initiated pipeline `.Stop()` was verified independently to throw `pipeline has been stopped` and create a `finally` marker. The behavioral launcher test uses this supported pipeline interruption and proves manifest finalization plus validation config/data/index removal. It does not claim that `Stop-Process`, `TerminateProcess`, or `CTRL_BREAK_EVENT` executes `finally`.
- Plain Bash `--validate` and PowerShell `-Validate` now have behavioral coverage proving UI startup, legacy smoke execution, PASS output, and isolated cleanup while smoke-only compatibility remains covered.

```text
focused GREEN
4 passed in 83.36s

fast-exit ownership-gate regression plus lifecycle tests
4 passed in 50.33s

pytest tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py -vv --tb=short
91 passed in 303.45s

ruff check tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py
All checks passed!

ruff format --check tests/unit/scripts/test_recorded_video_runtime_launcher.py tests/unit/scripts/test_es_runtime_stack_script.py
2 files already formatted

bash -n scripts/es-runtime-stack.sh
PASS

PowerShell Language.Parser.ParseFile scripts/es-runtime-stack.ps1
PowerShell parser: OK

git diff --check
PASS

temporary-repo command line and parent-lineage residual scan
none
```

One intermediate full-suite retry reached the 720-second outer timeout without a pytest summary. Its post-timeout owned-process scan was empty. The immediately following `-vv` full run completed all 91 tests in 303.45 seconds and did not identify a repeatable single-test stall; this remains a Windows process-startup timing risk rather than evidence of a forced-cleanup success.
