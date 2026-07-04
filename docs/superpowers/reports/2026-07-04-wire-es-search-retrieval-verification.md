# Wire ES Search Retrieval Verification

## Local Unit Verification

Command:

```powershell
pytest tests/unit/tools/test_embed_search.py tests/unit/api/test_video_search_ingest.py tests/unit/scripts/test_es_ingest_smoke.py -q
```

Result:

```text
27 passed, 1 warning
```

The warning is the existing FastAPI/Starlette `TestClient` deprecation warning.

## OpenSpec Verification

Command:

```powershell
npx openspec validate wire-es-search-retrieval
```

Result:

```text
Change 'wire-es-search-retrieval' is valid
```

## Runtime ES Validation

Command:

```powershell
docker --version
```

Result:

```text
docker: The term 'docker' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

Runtime ES startup was not executed on this machine because Docker CLI is not
available in the current environment. The Docker Compose file and PowerShell
start/stop/probe scripts were added so the same validation can be run once
Docker is available locally or through a server shell.

## Mapped Server Sync

Target:

```text
Z:\vsa-agent
```

Result:

```text
PASS: synced 18 files to Z:\vsa-agent
```

The sync copied the ES retrieval code, tests, runtime scripts, design docs,
plan, and active OpenSpec change files.

## Mapped Server Test Attempt

Command attempted from `Z:\vsa-agent`:

```powershell
$env:PYTHONPATH='Z:\vsa-agent\src'
pytest tests/unit/tools/test_embed_search.py tests/unit/api/test_video_search_ingest.py tests/unit/scripts/test_es_ingest_smoke.py -q
```

Result:

```text
39 failed, 1938 passed, 12 skipped
```

Root-cause investigation showed that the same path-filtered pytest command
collects only the target file locally, but in the `Z:` mapped directory pytest
collects the broader test suite even when explicit paths and `--rootdir` are
provided. There are no `PYTEST_*` environment variables, and Python imports
`vsa_agent` from `Z:\vsa-agent\src`, so this is recorded as a mapped-drive
pytest collection/runtime environment blocker rather than an ES implementation
failure.

The broad-suite failures include pre-existing report-language expectation
failures and missing `bash` process execution from the mapped working
directory. They are outside this ES retrieval change.
