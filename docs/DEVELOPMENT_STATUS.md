# Development Status

Last updated: 2026-07-04

## Current State

- Active OpenSpec change: `verify-es-ingest-runtime`.
- Active branch: `codex/es-real-service-validation`.
- Goal: add an opt-in runtime smoke path proving `/api/search/ingest` writes to a real Elasticsearch index.
- Default `config.yaml` still keeps `search.enabled: false`; runtime validation uses an explicit temporary config.
- The smoke script is `scripts/es_ingest_smoke.py`.

## Git Policy

- Develop on local temporary branches or worktrees.
- Prefer branches for ordinary single-threaded work.
- Use worktrees only when parallel local runtimes, side-by-side comparison, or a long-running isolated experiment is genuinely useful.
- For small safe documentation/configuration tweaks on a clean `master`, avoid unnecessary branch/worktree churn.
- Merge completed work into local `master`.
- Push `master` to origin.
- Keep remote branches cleaned up; this project does not normally use PR branches.

## Parallel Development Policy

- Comet decides whether work should be parallelized.
- Parallel work must use the relevant Comet/Superpowers skills, such as `dispatching-parallel-agents` or `subagent-driven-development`.
- The main session remains responsible for integration, verification, cleanup, and the final local merge to `master`.

## Latest Verified Change

`wire-es-ingest`

- Added real `/api/search/ingest` behavior.
- Uses `SearchBackendConfig`.
- Returns `skipped` when search indexing is disabled or not configured.
- Indexes one normalized metadata document to `search.embed_index` when enabled.
- Returns HTTP 502 for Elasticsearch indexing failures.
- Registers the ingest route in the FastAPI app.

Verification:

```powershell
python -m pytest tests\unit\api\test_video_search_ingest.py tests\unit\api\test_original_ui_chat.py tests\unit\api\test_original_ui_chat_route.py tests\unit\test_config_search.py tests\unit\tools\test_embed_search.py tests\unit\tools\test_attribute_search.py tests\unit\tools\test_search.py tests\unit\agents\test_search_agent.py -q
```

Result: `79 passed, 1 warning`.

```powershell
npx openspec validate wire-es-ingest
```

Result: valid before archive.

## Active Runtime Validation

Current command for the next validation pass:

```powershell
python scripts\es_ingest_smoke.py --api-url http://127.0.0.1:8000 --es-endpoint <endpoint> --index vsa-video-embeddings
```

Operational guide: `docs/es-ingest-runtime-validation.md`.

## Next Recommended Work

Finish `verify-es-ingest-runtime` through Comet verification, then merge locally to `master` and push only `master` to origin.
