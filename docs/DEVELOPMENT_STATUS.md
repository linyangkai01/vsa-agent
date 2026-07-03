# Development Status

Last updated: 2026-07-03

## Current State

- Local `master` includes the completed ES ingest change.
- `wire-es-ingest` has been archived into OpenSpec.
- The main recorded-video business-flow spec now includes the Elasticsearch video search ingest requirement.
- No active OpenSpec change is in progress.

## Git Policy

- Develop on local temporary branches or worktrees.
- Merge completed work into local `master`.
- Push `master` to origin.
- Keep remote branches cleaned up; this project does not normally use PR branches.

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

## Next Recommended Work

Start a new Comet change for the next ES milestone. Good candidates:

1. Verify ES ingest against a real Elasticsearch service and document the server validation path.
2. Add an end-to-end original UI search ingest smoke test.
3. Add operational docs for ES index setup and example ingest payloads.
