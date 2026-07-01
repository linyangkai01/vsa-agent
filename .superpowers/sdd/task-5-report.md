# Task 5 Report: Archive CLI Commands

## What changed
- Added `archive ingest` and `archive search` CLI handling in `src/vsa_agent/__main__.py`.
- Added `tests/unit/test_archive_cli.py` to cover ingest summary output and archive search output.

## Implementation notes
- `archive ingest` now calls `ingest_live_run(run_dir, index_path)` and prints a JSON summary containing:
  - `records_written`
  - `index_path`
  - `record_id`
- `archive search` now uses `LocalArchiveSearchStore(index_path).search(query=..., top_k=...)` and prints the resulting search payload as JSON.
- The existing `config` and `validate-run` flows were left unchanged.

## Verification
- Ran: `python -m pytest tests/unit/test_archive_cli.py -q`
- Initial run failed during `tmp_path` setup with Windows `PermissionError` on `C:\Users\81945\AppData\Local\Temp\pytest-of-81945`.
- Retried with the requested isolated basetemp:
  - `python -m pytest tests/unit/test_archive_cli.py -q --basetemp=tmp\pytest-task5`
- That run still failed during pytest session cleanup with Windows `PermissionError` on `D:\WorkPlace\vsa-agent\tmp\pytest-task5`.

## Notes
- The test file and CLI wiring match the task brief and stay within the requested file scope.
- The remaining blocker is environment-specific pytest temp directory access on Windows, not a code-level exception in the archive CLI path.
