# Development Status

Last updated: 2026-07-12

## Current State

- Active OpenSpec change: `script-es-runtime-stack`.
- Active branch: `codex/script-es-runtime-stack`.
- Goal: provide an interactive Windows/Linux ES, API and original-UI launcher that verifies the original `/api/v1/search` business flow.
- Default `config.yaml` still keeps `search.enabled: false`; runtime validation uses an explicit temporary config.
- Stack wrappers: `scripts/es-runtime-stack.ps1`, `scripts/es-runtime-stack.sh`.
- Smoke script: `scripts/es_ingest_smoke.py`.

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

- `script-es-runtime-stack`: building stack commands that start ES, start FastAPI with a temporary search-enabled config, run ingest/search smoke validation, and clean up owned resources.
- Next server validation command: `./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings`.

## Active Runtime Validation

Current command for the next validation pass:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
```

Operational guide: `docs/superpowers/reference/es-video-search-runtime.md`.

Server validation status: backend ES/API smoke validation has passed on Ubuntu after the named Docker volume, async client, ES 8.x client, mapping, and deterministic smoke-query fixes. Original UI startup was blocked by unavailable `npm`; the active launcher now bootstraps a repository-local Node runtime, validates Python dependencies before launch, and writes UI/API/ES failure diagnostics. Sync and browser validation remain pending. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`. Current Codex sandbox attempts can read `Z:\vsa-agent` but receive `Access denied` on writes; if that happens, run the same script from the normal Windows PowerShell session that owns the `Z:` mapping.

## Next Recommended Work

Finish `script-es-runtime-stack` through Comet verification, sync changed files to `Z:\vsa-agent`, then merge locally to `master` and push only `master` to origin.
