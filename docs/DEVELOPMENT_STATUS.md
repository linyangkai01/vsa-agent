# Development Status

Last updated: 2026-07-13

## Current State

- Active OpenSpec changes on `master`: none.
- The five-change Python quality program is implemented, verified and archived.
- Recorded-video development remains isolated on `codex/production-recorded-video-ingest`; its runtime code and active OpenSpec artifacts are not part of this `master` integration.
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

`refactor-search-orchestration`

- Centralized search routing, result normalization, highest-score deduplication, confidence fallback, critic filtering and top-k trimming in `search_pipeline.py`.
- Kept models, external I/O, stage logging, critic calls, progress order and registration in `search.py`.
- Archived the OpenSpec change and merged its four requirements into the main specification.
- Search path matrix: `75 passed, 1 warning`.

## Active Change

- No active change is present on `master`.
- `production-recorded-video-ingest` remains in progress on `codex/production-recorded-video-ingest`; resume from task 1.2 after this quality integration.

## Python Quality Program

The repository-wide Python quality work was completed as five ordered Comet changes. `frontend/original-ui` was excluded from code-quality refactoring. All five changes are archived.

- `stabilize-test-contracts`: archived. `tests/unit/recorded_video/__init__.py` gives future recorded-video tests a package-qualified module name while `archive/test_models.py` remains distinct.
- `enforce-python-quality-baseline`: archived. Ruff lint and format debt is cleared in `src/` and `tests/`.
- `consolidate-runtime-scripts`: archived. All 14 user entries remain, the DashScope wrappers share one preflight helper, and stale archived-change paths no longer block server sync preflight.
- `refactor-video-understanding-pipeline`: archived. Pure normalization is isolated from the stable I/O facade while public contracts and monkeypatch paths remain intact.
- `refactor-search-orchestration`: archived. Routing, normalization, deduplication, confidence fallback, critic filtering and trimming use one pure rule module.

Test collection verification on 2026-07-13:

```powershell
pytest --collect-only -q
pytest -q
```

Result: `763 tests collected`; `759 passed, 4 skipped, 1 warning`.

Python quality baseline verification on 2026-07-13:

```powershell
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: compileall passed; Ruff reported zero lint issues; all 235 files were already formatted; `759 passed, 4 skipped, 1 warning`. The warning is the existing Starlette `httpx` deprecation from the installed environment.

Runtime script consolidation verification on 2026-07-13:

```powershell
Get-ChildItem scripts -Recurse -Filter *.sh | ForEach-Object { bash -n $_.FullName }
Get-ChildItem scripts -Recurse -Filter *.ps1 | ForEach-Object { [void][scriptblock]::Create((Get-Content -Raw $_.FullName)) }
pytest -q tests/unit/test_dashscope_live_runner.py tests/unit/scripts
ruff check src tests
ruff format --check src tests
pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-server-files.ps1 -PreflightOnly
```

Result: all scripts parsed; `58` script tests passed; Ruff reported zero issues and 235 formatted files; `760 passed, 4 skipped, 1 warning`; mapped target preflight passed for 36 files. The 14 user script entries remain supported, while the two DashScope entries now share `scripts/lib/dashscope_runtime.sh`.

Video-understanding pipeline verification on 2026-07-13:

```powershell
pytest -q tests/unit/tools/test_video_understanding_normalization.py tests/unit/tools/test_video_understanding.py tests/unit/tools/test_video_understanding_live_trace.py tests/unit/tools/test_lvs_video_understanding.py tests/unit/data_models/test_understanding_models.py tests/acceptance/test_video_understanding_flow.py
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: the video path matrix passed 96 tests; Ruff reported zero issues and 237 formatted files; the current full tree passed `782 passed, 4 skipped, 1 warning`. `video_understanding_normalization.py` owns pure time, reasoning, evidence, event and result conversion; `video_understanding.py` keeps stable frame/VLM/source/tool boundaries and compatibility imports; LVS directly consumes the pure timestamp helper.

Search-orchestration verification on 2026-07-13:

```powershell
pytest -q tests/unit/tools/test_search_pipeline.py tests/unit/tools/test_search.py tests/unit/tools/test_embed_search.py tests/unit/tools/test_attribute_search.py tests/unit/agents/test_search_agent.py tests/unit/api/test_original_ui_search_route.py tests/acceptance/test_search_flow.py
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
```

Result: the search path matrix passed 75 tests; Ruff reported zero issues and 239 formatted files; the final development branch passed `795 passed, 4 skipped, 1 warning`. `search_pipeline.py` owns pure routing and result-selection rules; `search.py` retains models, external dependency boundaries, stage logs, critic calls, progress order and registration.

Master integration verification on 2026-07-13:

```powershell
python -m compileall -q src tests
ruff check src tests
ruff format --check src tests
pytest -q
openspec validate --all
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-server-files.ps1 -PreflightOnly
```

Result: compileall and Ruff passed; 233 files were formatted; `721 passed, 4 skipped, 1 warning`; all 9 main OpenSpec specifications were valid; the mapped server preflight passed for 36 files. The warning remains the existing Starlette/httpx deprecation. The integration excludes recorded-video runtime code and its active change artifacts.

## Active Runtime Validation

Current command for the next validation pass:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
```

Operational guide: `docs/superpowers/reference/es-video-search-runtime.md`.

Server validation status: Ubuntu browser validation has passed. Through the SSH UI tunnel, the original Search UI returned one `runtime-validation.mp4` result for `forklift near worker`; API logs recorded both `original_ui.search.request` and `search_agent.embed_search`, and UI logs contained no stale declaration source-map errors. The evidence is recorded in `docs/superpowers/reports/2026-07-12-interactive-es-ui-validation.md`. The runtime remains a deterministic mock-embedding validation environment, not a production semantic-quality evaluation. `Z:\vsa-agent` is the mapped server project copy. Server sync should use the already-authenticated Windows mapped drive, not Git, so no server password is requested or stored by project scripts. Use `.\scripts\sync-server-files.ps1 -PreflightOnly` and then `.\scripts\sync-server-files.ps1` for targeted sync instead of recursive `robocopy /E`. Current Codex sandbox attempts can read `Z:\vsa-agent` but receive `Access denied` on writes; if that happens, run the same script from the normal Windows PowerShell session that owns the `Z:` mapping.

## Next Recommended Work

Resume `production-recorded-video-ingest` on `codex/production-recorded-video-ingest` from task 1.2, keeping its Comet artifacts and runtime implementation isolated until that change passes verification.
