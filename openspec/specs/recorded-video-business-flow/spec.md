# recorded-video-business-flow

## Purpose

Define the open recorded-video business-flow baseline for `vsa-agent`.
This capability preserves the useful NVIDIA VSS recorded-video behaviors
without requiring NVIDIA runtime services.
## Requirements
### Requirement: Shared recorded-video validation

The system SHALL run a configured local video through shared-mode video understanding, QA output, report output, artifact writing, and run validation without requiring NVIDIA runtime services.

#### Scenario: Shared mode succeeds

- GIVEN `config.yaml` resolves an active profile and video path
- WHEN the user runs `bash scripts/run_live_top_agent_video_dashscope.sh`
- THEN the run writes `manifest.json`, `trace.jsonl`, `qa-final.txt`, and `report-final.txt`
- AND `conda run -n vsa-agent python -m vsa_agent validate-run <run_dir>` returns PASS

### Requirement: Graph recorded-video validation

The system SHALL run graph mode with TopAgent tool-call evidence while avoiding duplicate long-video VLM understanding for QA and report phases.

#### Scenario: Graph mode succeeds without repeated LVS

- GIVEN `VSA_LIVE_VIDEO_MODE=graph`
- WHEN the user runs `bash scripts/run_live_top_agent_video_dashscope.sh`
- THEN the trace includes `top_agent.agent.request`, `top_agent.agent.response`, `top_agent.tool.call`, `top_agent.tool.result`, and `top_agent.final`
- AND validator summary includes model call counts and token counts
- AND validator does not emit a repeated long-video understanding warning

### Requirement: Local archive search validation

The system SHALL validate a local archive search flow without Elasticsearch, NVIDIA Cosmos, or RTVI services.

#### Scenario: Local archive search returns deterministic result

- GIVEN a deterministic local archive fixture with at least one video metadata record
- WHEN `search_agent` receives a matching natural-language query
- THEN it returns a `SearchOutput` with at least one `SearchResult`
- AND the result contains video name, description, timestamps, sensor id, similarity, and object ids

### Requirement: Elasticsearch video search ingest

The system SHALL provide a recorded-video search ingest API that indexes caller-provided video search metadata into Elasticsearch when search indexing is enabled, and the project SHALL provide a repeatable runtime validation path for verifying that ingest against a real Elasticsearch service.

#### Scenario: Search ingest skips when Elasticsearch is disabled

- **WHEN** `/api/search/ingest` receives a valid video ingest request and `search.enabled` is false
- **THEN** the response reports `status` as `skipped`
- **AND** the response reports `indexed` as false
- **AND** no Elasticsearch index operation is attempted

#### Scenario: Search ingest writes to configured Elasticsearch index

- **WHEN** `/api/search/ingest` receives a valid video ingest request and `search.enabled` is true with `search.es_endpoint` set
- **THEN** the system writes one document to `search.embed_index`
- **AND** the indexed document includes `video_id`, `video_name`, `description`, `sensor_id`, timestamps, screenshot URL, and vector metadata when supplied
- **AND** the response reports `status` as `ingested`, `indexed` as true, and the Elasticsearch result id

#### Scenario: Search ingest reports Elasticsearch failure

- **WHEN** Elasticsearch rejects or fails the ingest request
- **THEN** `/api/search/ingest` returns a clear 502 error
- **AND** the response does not claim that indexing succeeded

#### Scenario: Real Elasticsearch ingest smoke validation succeeds

- **GIVEN** a reachable Elasticsearch service and project configuration with `search.enabled` true, `search.es_endpoint` set, and `search.embed_index` set
- **WHEN** the runtime validation path starts the API service and posts a representative video ingest payload to `/api/search/ingest`
- **THEN** the endpoint returns `status` as `ingested`, `indexed` as true, and a non-empty Elasticsearch result id
- **AND** querying the configured Elasticsearch index returns the document with the submitted `video_id`, description, sensor id, timestamps, screenshot URL, vector metadata, and original metadata
- **AND** the validation instructions identify the exact commands, configuration values, and expected success output needed to repeat the smoke test locally or on the documented validation server

### Requirement: Elasticsearch video segment search retrieval

The system SHALL search recorded-video segment index records from Elasticsearch when search indexing is enabled and records have been written to the configured embed index.

The indexed Elasticsearch records SHALL represent searchable video segments, not stored video files and not Enterprise RAG knowledge-base documents.

#### Scenario: Embed search returns an ingested Elasticsearch video segment record

- **GIVEN** `search.enabled` is true, `search.es_endpoint` is set, and `search.embed_index` contains a video segment record written by `/api/search/ingest`
- **WHEN** the project runs an embed-only recorded-video search whose query matches that record
- **THEN** the search returns a `SearchOutput` containing a `SearchResult` for the indexed video segment record
- **AND** the result includes video name, description, timestamps, sensor id, screenshot URL, and similarity

#### Scenario: Ingested record preserves video segment identity

- **GIVEN** `/api/search/ingest` receives metadata containing video/source identity, description, timestamp range, vector, and screenshot URL fields
- **WHEN** the endpoint indexes the record into Elasticsearch
- **THEN** the indexed record contains stable top-level fields for `video_id`, `video_name`, `description`, `sensor_id`, `start_time`, `end_time`, `screenshot_url`, and `vector`
- **AND** the original metadata is preserved for forward compatibility

#### Scenario: Video files remain outside Elasticsearch

- **GIVEN** a recorded video has been indexed for search
- **WHEN** a search result is returned from Elasticsearch
- **THEN** the result references the video segment by source id, timestamp range, and URL fields
- **AND** Elasticsearch is not treated as the storage location for the video bytes

#### Scenario: Enterprise RAG document knowledge is out of scope

- **WHEN** the recorded-video search path indexes or searches Elasticsearch
- **THEN** it only handles video segment search records
- **AND** it does not create or query SOP, manual, policy, or other Enterprise RAG document collections

#### Scenario: Search falls back when Elasticsearch retrieval is unavailable

- **GIVEN** Elasticsearch search is disabled, unreachable, missing the configured index, or rejects the ES query
- **WHEN** the project runs an embed-only recorded-video search
- **THEN** the search path preserves the existing fallback behavior and does not require a running Elasticsearch service for normal unit tests

### Requirement: Scriptable Elasticsearch development runtime

The project SHALL provide scripts and configuration for starting a single-node Elasticsearch development service that can be used for local or mapped-server validation.

#### Scenario: Development Elasticsearch service starts from script

- **WHEN** the user runs the documented ES startup script in a project checkout with Docker Compose available
- **THEN** a single-node Elasticsearch service starts with the configured HTTP port
- **AND** the script reports the endpoint that should be used as `search.es_endpoint`

#### Scenario: Server project receives runnable Elasticsearch setup

- **GIVEN** the mapped server project is available at `Z:\vsa-agent`
- **WHEN** implementation is completed and synced
- **THEN** the Elasticsearch startup scripts, Compose configuration, and validation instructions are present in the server project
- **AND** any missing server-side execution dependency is recorded clearly instead of being reported as a successful runtime validation

