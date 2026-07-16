# Task 22 Launcher Report

Status: DONE_WITH_CONCERNS

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
