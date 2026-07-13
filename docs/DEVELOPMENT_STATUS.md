# Development Status

Last updated: 2026-07-12

## Current State

- Active OpenSpec change: `production-recorded-video-ingest`.
- Active branch: `codex/production-recorded-video-ingest`.
- Phase: design is approved and the detailed implementation plan is ready for execution-mode selection.
- Goal: evolve the existing original-UI/Elasticsearch smoke path into a real recorded-video upload, durable analysis, semantic indexing, search, thumbnail and time-range playback flow without NVIDIA runtime services.
- Confirmed first-stage runtime: single Ubuntu server, local file storage, SQLite WAL jobs, independent Worker, OpenAI-compatible VLM/embedding, fixed-duration replaceable segmentation, and one stack launcher.
- Out of scope for this change: RTSP, alerts, Kafka/MDX, multi-node deployment, MinIO/S3, Redis/Celery and full VST emulation.

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

## Active Change

- `production-recorded-video-ingest`: OpenSpec and Chinese design artifacts are approved; the 24-task TDD implementation plan is ready for Comet execution-mode selection.
- Design document: `docs/superpowers/specs/2026-07-12-production-recorded-video-ingest-design.md`.
- Implementation plan: `docs/superpowers/plans/2026-07-13-production-recorded-video-ingest.md`.
- No implementation code has been started for this change.

## Active Runtime Validation

Current command for the next validation pass:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
```

Operational guide: `docs/superpowers/reference/es-video-search-runtime.md`.

Server validation status: Ubuntu browser validation has passed. Through the SSH UI tunnel, the original Search UI returned one `runtime-validation.mp4` result for `forklift near worker`; API logs recorded both `original_ui.search.request` and `search_agent.embed_search`, and UI logs contained no stale declaration source-map errors. The evidence is recorded in `docs/superpowers/reports/2026-07-12-interactive-es-ui-validation.md`. The runtime remains a deterministic mock-embedding validation environment, not a production semantic-quality evaluation. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`. Current Codex sandbox attempts can read `Z:\vsa-agent` but receive `Access denied` on writes; if that happens, run the same script from the normal Windows PowerShell session that owns the `Z:` mapping.

## Next Recommended Work

Choose whether to continue from the Comet plan-ready gate; if continuing, select isolation, execution, TDD and review modes before writing code.
