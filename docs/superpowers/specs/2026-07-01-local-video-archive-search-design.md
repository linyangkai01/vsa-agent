# Local Video Archive Search Design

## Purpose

This phase closes the local recorded-video search loop for `vsa-agent`.
The project can already run a real local video through TopAgent, save run artifacts, and validate the run. The next capability is to turn those real run artifacts into a lightweight local archive that `search_agent` can search without requiring Elasticsearch, NVIDIA services, or a remote vector database.

This supports the project goal: replace the original NVIDIA VSS stack with an open, self-owned `vsa-agent` business flow while keeping the same core behavior: analyze recorded video, persist useful searchable evidence, and answer later search queries over that archive.

## Scope

Build a minimal local archive search loop:

- Ingest one or more `artifacts/live-video-runs/<run_id>` directories into a local JSONL archive.
- Extract searchable text from `manifest.json`, `qa-final.txt`, `report-final.txt`, and selected tool-result artifacts when present.
- Convert each ingested run into a `SearchResult` compatible record.
- Search the archive with a deterministic local text scorer.
- Expose the search store through `search_agent` using the existing `embed_search` injection/registry pattern.
- Add CLI commands so a developer can ingest and search without writing Python snippets.
- Add tests that prove a real-shaped run artifact can be ingested and found by `search_agent`.

## Non-Goals

- Do not introduce Elasticsearch, Milvus, LanceDB, or another persistent vector database in this phase.
- Do not call live LLM/VLM APIs during archive ingest or search.
- Do not re-run video understanding during archive ingest.
- Do not redesign `SearchResult`, `SearchOutput`, or the existing search agent contract.
- Do not solve report quality in this phase.

## Architecture

Add a focused `vsa_agent.archive` package. It owns local archive records, JSONL persistence, artifact parsing, and deterministic text search.

The archive module stays below the agent layer:

```text
live-video-runs/<run_id>
  -> archive.ingest.ingest_live_run()
  -> artifacts/video-archive/index.jsonl
  -> archive.search.LocalArchiveSearchStore.search()
  -> SearchOutput
  -> search_agent.execute_search_agent_flow()
```

This preserves the existing `search_agent` and `search_tool` boundaries. The first implementation can be dependency-injected in acceptance tests and optionally wired into default local search later through configuration.

## Data Model

`ArchiveRecord` is the internal persistence model:

- `record_id`: stable ID, normally the live run ID.
- `video_name`: basename of the analyzed video.
- `video_path`: original local video path from `manifest.json`.
- `description`: best concise searchable description.
- `search_text`: concatenated text used for local scoring.
- `start_time`: ISO-like timestamp from manifest `started_at` or empty string.
- `end_time`: ISO-like timestamp from manifest `ended_at` or empty string.
- `sensor_id`: derived from video stem or manifest source metadata.
- `screenshot_url`: empty string unless future frame preview metadata exists.
- `object_ids`: extracted lightweight tags such as `person`, `forklift`, `vehicle`, when found.
- `metadata`: run directory, mode, model names, QA/report status, and source artifact paths.

The public search output remains `SearchOutput(data=list[SearchResult])`.

## Search Behavior

The local scorer should be deterministic and transparent:

- Normalize query and record text to lowercase word tokens.
- Score by token overlap, with a small boost for phrase containment.
- Return top `k` records sorted by score descending.
- Convert score to `similarity` in the `0.0` to `1.0` range.
- Return an empty `SearchOutput` for an empty archive or no matching tokens.

This is intentionally simple. It makes the business flow testable now and leaves a clean seam for embeddings later.

## CLI

Extend `python -m vsa_agent` with archive commands:

```bash
python -m vsa_agent archive ingest artifacts/live-video-runs/20260701-102652 --index artifacts/video-archive/index.jsonl
python -m vsa_agent archive search "forklift safety risk" --index artifacts/video-archive/index.jsonl --top-k 5
```

The ingest command prints a small JSON summary including `records_written`, `index_path`, and `record_id`.
The search command prints a JSON `SearchOutput` compatible payload.

## Error Handling

- Missing run directory: fail with a clear `FileNotFoundError`-style CLI message and non-zero exit.
- Missing `manifest.json`: fail ingest because the run identity and video path are not trustworthy.
- Missing `qa-final.txt` or `report-final.txt`: continue ingest using whichever text artifacts exist.
- Invalid JSONL line in an existing index: skip the bad line during search and keep searching valid records.
- Duplicate `record_id`: replace the previous record so repeated ingest is idempotent.

## Tests

Add unit tests for:

- Parsing a synthetic live run directory into one `ArchiveRecord`.
- JSONL index idempotent upsert behavior.
- Local search scoring and no-match behavior.
- CLI argument handling for ingest/search.

Add acceptance coverage for:

- Create a real-shaped live run artifact fixture.
- Ingest it into a temp archive index.
- Search with `execute_search_agent_flow(..., agent_mode=False, use_critic=False, embed_search=archive_store.search_callable(...))`.
- Assert the returned `SearchResult` references the original video and the text answer mentions a relevant term such as `forklift`.

## Acceptance Criteria

- A developer can run one command to ingest a live video run artifact into a local archive index.
- A developer can run one command to search that archive and see matching video metadata.
- `search_agent` can search the local archive through the existing flow.
- No live API key is required for archive ingest/search tests.
- Existing live video acceptance and validator behavior remains unchanged.
