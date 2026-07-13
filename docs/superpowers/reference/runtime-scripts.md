# Runtime Script Inventory

Last audited: 2026-07-13

`scripts/` contains 14 supported user or lifecycle entry points. The audit found no deletion candidate: every entry has a caller in documentation, tests, `package.json`, or another script. `scripts/lib/dashscope_runtime.sh` is an internal sourced helper and is not a user entry point.

| Script | Platform | Responsibility | Caller evidence | Verification | Decision |
| --- | --- | --- | --- | --- | --- |
| `bootstrap_node.sh` | Bash | Install/select the repository Node runtime | `install_original_ui_deps.sh`, UI runtime docs | `bash -n scripts/bootstrap_node.sh` | Keep |
| `es-dev-probe.ps1` | PowerShell | Probe local Elasticsearch readiness | `es-runtime-stack.ps1`, ES runtime tests/docs | PowerShell parse; stack tests | Keep |
| `es-dev-start.ps1` | PowerShell | Start the owned Elasticsearch development container | `es-runtime-stack.ps1`, ES runtime docs | PowerShell parse; stack tests | Keep |
| `es-dev-stop.ps1` | PowerShell | Stop the owned Elasticsearch development container | `es-runtime-stack.ps1`, ES runtime docs | PowerShell parse; stack tests | Keep |
| `es-runtime-stack.ps1` | PowerShell | Orchestrate ES, API and original UI on Windows | ES runtime docs and script tests | PowerShell parse; `test_es_runtime_stack_script.py` | Keep; frozen here |
| `es-runtime-stack.sh` | Bash | Orchestrate ES, API and original UI on Linux | ES runtime docs and script tests | `bash -n`; `test_es_runtime_stack_script.py` | Keep; frozen here |
| `es_ingest_smoke.py` | Python | Validate Elasticsearch ingest and search API flow | both ES stack launchers and smoke tests | `pytest -q tests/unit/scripts/test_es_ingest_smoke.py` | Keep |
| `install_original_ui_deps.sh` | Bash | Install original UI dependencies | runtime documentation | `bash -n scripts/install_original_ui_deps.sh` | Keep |
| `run_live_acceptance_dashscope.sh` | Bash | Run evaluator live API acceptance against DashScope | development plan and runner tests | `test_dashscope_live_runner.py`; `bash -n` | Keep entry; share preflight |
| `run_live_top_agent_video_dashscope.sh` | Bash | Run TopAgent video acceptance against DashScope | development plan and runner tests | `test_dashscope_live_runner.py`; `bash -n` | Keep entry; share preflight |
| `run_original_ui_debug_stack.sh` | Bash | Start the original UI debug stack | runtime documentation | `bash -n scripts/run_original_ui_debug_stack.sh` | Keep |
| `run_original_ui_vss.sh` | Bash | Start the original UI VSS application | ES stack launchers and runtime docs | `bash -n scripts/run_original_ui_vss.sh`; stack tests | Keep |
| `smoke_original_ui_chat.sh` | Bash | Exercise original UI chat streaming | package command and runtime docs | `bash -n scripts/smoke_original_ui_chat.sh` | Keep |
| `sync-server-files.ps1` | PowerShell | Sync approved project files to mapped server | runtime docs and server workflow | PowerShell parse; `-PreflightOnly` | Keep; frozen here |

## Consolidation Boundary

Only the duplicated DashScope preflight is consolidated. Windows/Linux pairs remain separate because they own platform-specific process and lifecycle behavior. ES, UI, smoke, installation and sync scripts remain separate because their responsibilities and callers differ.

## Deletion Rule

A script can be deleted only after all documentation, tests, package commands and script callers migrate to a replacement and a full-repository filename scan returns no dangling reference. No current script meets that rule.
