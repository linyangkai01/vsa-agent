# script-es-runtime-stack Verification

## Summary

- Change: `script-es-runtime-stack`
- Result: PASS for offline unit/static/OpenSpec validation.
- Runtime stack validation: BLOCKED in the current local shell.

## Evidence

Offline/static validation passed:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
```

Result:

```text
14 passed in 0.60s
```

OpenSpec validation passed:

```powershell
npx openspec validate script-es-runtime-stack
```

Result:

```text
Change 'script-es-runtime-stack' is valid
```

PowerShell parse validation passed:

```powershell
powershell -NoProfile -Command "`$null = [scriptblock]::Create((Get-Content -Raw scripts\es-runtime-stack.ps1)); 'PASS'"
```

Result:

```text
PASS
```

## Runtime Attempt

First attempt:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

Result:

```text
API port 8000 is already in use. Pass -ApiPort with another value.
```

Second attempt with an alternate API port:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8010 -EsPort 9200
```

Result:

```text
docker : The term 'docker' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

Runtime validation is therefore blocked until Docker is available in the execution environment, or the command is run from a server shell where Docker Compose is installed and available on PATH.

Follow-up server attempt from Ubuntu showed that PowerShell Core is not installed:

```text
Command 'pwsh' not found
```

A Linux bash wrapper was added so the Ubuntu server can validate without
installing PowerShell Core:

```bash
cd /data/project/lyk/vsa-agent
chmod +x ./scripts/es-runtime-stack.sh
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --index vsa-video-embeddings --stop-elasticsearch
```

Linux wrapper static contract validation passed locally:

```powershell
pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
```

Result:

```text
19 passed
```

Local `bash -n scripts/es-runtime-stack.sh` could not run in this Windows thread
because Git Bash failed with `couldn't create signal pipe, Win32 error 5`; run
the script on the Ubuntu server for native bash validation.

## Server Sync

Server sync is configured to use the already-authenticated Windows mapped drive
at `Z:\vsa-agent`. Project scripts do not request or store the server password.

The targeted sync helper passed dry-run manifest validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1 -DryRun
```

Result:

```text
PASS: dry run completed for selected files
```

The mapped-drive write preflight is currently blocked in this Codex sandbox:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1 -PreflightOnly
```

Result:

```text
Access denied while writing to mapped target 'Z:\vsa-agent'.
```

Run the same command from the normal Windows PowerShell session that owns the
`Z:` mapping, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-server-files.ps1
```

## Review Gate

Automatic reviewer dispatch was skipped because the available subagent tool
requires explicit user authorization for delegation/parallel agent work. Local
verification commands above were run instead.
