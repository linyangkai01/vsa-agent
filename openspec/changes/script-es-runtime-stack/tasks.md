## 1. Runtime Stack Design

- [ ] 1.1 Confirm the stack wrapper boundaries around existing ES lifecycle scripts, FastAPI startup, temporary config, smoke validation, and cleanup.
- [ ] 1.2 Identify the minimal testable units for stack behavior without requiring Docker or a live API in normal unit tests.

## 2. Stack Script Implementation

- [ ] 2.1 Add a PowerShell stack validation script that starts ES, writes a temporary search-enabled config, starts FastAPI, waits for health, runs `scripts/es_ingest_smoke.py`, and prints PASS/FAIL.
- [ ] 2.2 Add a companion stop or cleanup path that stops only owned API processes and uses the existing ES stop behavior.
- [ ] 2.3 Add focused tests or static checks for config generation, health probing, command construction, and failure messages where practical.

## 3. Documentation And Server Sync

- [ ] 3.1 Update ES runtime documentation with one-command local validation, mapped-server `Z:\vsa-agent` usage, expected output, and troubleshooting.
- [ ] 3.2 Update development status or verification notes so the project state clearly shows this change is in progress.
- [ ] 3.3 Sync completed scripts and docs to `Z:\vsa-agent` after local implementation.

## 4. Verification And Closeout

- [ ] 4.1 Run focused unit/static validation for the new scripts.
- [ ] 4.2 Run OpenSpec validation for `script-es-runtime-stack`.
- [ ] 4.3 Attempt real stack validation if Docker and the runtime environment are available; otherwise record the exact blocker.
- [ ] 4.4 Finish on the local development branch, merge locally to `master`, push only remote `master`, and archive the Comet change after verification passes.
