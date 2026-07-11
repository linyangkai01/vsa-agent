# Development Status

Last updated: 2026-07-11

## Current State

- Active OpenSpec changes:
  - `stabilize-test-contracts` on `feature/20260710/stabilize-test-contracts`: report-flow tests now validate Markdown structure and report data without binding output language; configuration diagnostics and DashScope runners isolate missing-key behavior.
  - `script-es-runtime-stack` on `codex/script-es-runtime-stack`: ES runtime-stack validation remains active in its separate worktree.
- `stabilize-test-contracts` verification: focused suite `54 passed`; full suite `660 passed, 4 skipped, 1 warning` using a worktree-local temporary directory.
- The four skips remain conditional skips; no skip was converted to a failure or removed.

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

Server validation status: no documented external Elasticsearch/API validation server is configured in this repo yet, so no server sync or server-side smoke run was performed for this build pass. The smoke path is ready to run when a server API URL and Elasticsearch endpoint are supplied.

## Next Recommended Work

Finish `verify-es-ingest-runtime` through Comet verification, then merge locally to `master` and push only `master` to origin.
