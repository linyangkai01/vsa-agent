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

The system SHALL provide a recorded-video search ingest API that indexes
caller-provided video search metadata into Elasticsearch when search indexing
is enabled, and the project SHALL provide a scriptable runtime stack validation
path for verifying ES ingest and retrieval against a real Elasticsearch service
and FastAPI API process.

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

#### Scenario: Runtime stack smoke validation succeeds

- **GIVEN** Docker Compose can start the project Elasticsearch service and Python can start `vsa_agent.api.routes:app`
- **WHEN** the user runs the documented ES runtime stack validation script
- **THEN** the script starts Elasticsearch, creates a temporary search-enabled config, starts FastAPI with `VSA_CONFIG` pointing at that config, waits for `/health`, and runs the ingest-search smoke validation
- **AND** the smoke validation posts a representative video ingest payload to `/api/search/ingest`
- **AND** the endpoint returns `status` as `ingested`, `indexed` as true, and a non-empty Elasticsearch result id
- **AND** querying the configured Elasticsearch index returns the document with the submitted `video_id`, description, sensor id, timestamps, screenshot URL, vector metadata, and original metadata
- **AND** the script prints a clear PASS result that includes the API URL, ES endpoint, and index name

#### Scenario: Runtime stack validation cleans up owned services

- **WHEN** the ES runtime stack validation script completes or fails after starting services
- **THEN** it stops the FastAPI process that it started
- **AND** it provides or invokes the documented Elasticsearch stop behavior
- **AND** it removes or identifies any temporary config file created for validation

#### Scenario: Runtime stack reports environment blockers clearly

- **WHEN** Docker Compose, Python dependencies, Uvicorn, the configured ports, or the mapped server execution environment are unavailable
- **THEN** the validation path reports the missing dependency or blocked action clearly
- **AND** it does not report runtime smoke validation as successful
- **AND** the server sync documentation keeps the scripts available at `Z:\vsa-agent` for execution when the dependency is available

#### Scenario: Fresh runtime validation starts without a pre-existing ES index

- **GIVEN** the configured Elasticsearch index does not exist on a fresh runtime volume
- **WHEN** the smoke validation removes stale validation records before ingest
- **THEN** it skips stale-record deletion without treating the missing index as an Elasticsearch failure
- **AND** it continues to ingest the validation document so the API can create the configured index

#### Scenario: Windows interactive runtime confirms original UI readiness

- **GIVEN** interactive runtime mode starts the original UI process
- **WHEN** the UI process exits before serving its configured HTTP URL or exits non-zero after becoming ready
- **THEN** the launcher reports a validation failure with the process exit status
- **AND** it prints the UI stdout and stderr log paths for diagnosis

#### Scenario: Interactive runtime stack starts the original UI

- **GIVEN** the user selects interactive runtime mode
- **WHEN** the user runs the documented all-stack launcher
- **THEN** it starts Elasticsearch, FastAPI with the temporary search-enabled configuration, and the original UI
- **AND** it configures the original UI to use the FastAPI `/api/v1` base URL
- **AND** it retains the services until the user interrupts the launcher
- **AND** it prints the browser URL, API URL, ES endpoint, and configured index

#### Scenario: Original UI search resolves through Elasticsearch

- **GIVEN** interactive runtime mode has indexed the smoke video-search record
- **WHEN** a user submits a query through the original VSS Search UI
- **THEN** the UI sends its existing search request to `/api/v1/search`
- **AND** the API routes the request through the existing SearchAgent and registered `embed_search` tool
- **AND** the enabled runtime tool queries Elasticsearch and returns `{data: [...]}` in the original UI contract
- **AND** the original UI renders the returned video-search result
- **AND** API logs record the request and the `search_agent.embed_search` execution evidence

#### Scenario: Fast validation uses deterministic embeddings

- **GIVEN** the interactive runtime stack generates its temporary search-enabled configuration
- **WHEN** it runs the ingest smoke and the user submits the documented browser query
- **THEN** `search.force_mock_embedding` is enabled only in that temporary configuration
- **AND** the indexed record and ES query use the same deterministic mock embedding dimension
- **AND** the search route returns the Elasticsearch result rather than an in-memory fallback
- **AND** committed and production-style configurations keep `search.force_mock_embedding` disabled by default

#### Scenario: Interactive runtime stack reclaims requested ports

- **GIVEN** a process occupies the selected API, UI, or ES port
- **WHEN** the all-stack launcher starts
- **THEN** it logs the target port, PID, and command line before terminating the occupying process
- **AND** it waits for the selected port to be released before starting the replacement service
- **AND** if the port cannot be released, it fails without starting a partial stack
- **AND** it does not terminate processes that do not occupy a selected target port

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

### Requirement: Production recorded-video upload and recovery

The system SHALL accept real MP4/MKV files through the original UI upload contract, process them in an independent recoverable Worker, persist durable checkpoints in SQLite, and publish only complete segment projections to Elasticsearch.

#### Scenario: Three real uploads survive a Worker restart

- **GIVEN** three readable video files with distinct SHA-256 content and a production profile with mock fallback disabled
- **WHEN** the production acceptance runner uploads all three concurrently, interrupts the verified Worker after a durable checkpoint, and starts the same stack again
- **THEN** the second Worker completes all three jobs through `publish`
- **AND** at least one interrupted job is reclaimed with an increased attempt
- **AND** every completed pre-interruption manifest and checksum remains unchanged
- **AND** the seven pipeline checkpoints are complete and segment identities are unique

#### Scenario: Worker interruption is fail-closed

- **WHEN** the acceptance runner prepares to interrupt a Worker
- **THEN** it requires a current-run `processes.json` with exactly one active Worker entry
- **AND** it verifies the run ID, launcher-owned PID, current UID, runtime supervisor command, Worker command, config path, status path, and log paths
- **AND** it sends no signal when any identity evidence is missing or inconsistent

### Requirement: Original UI recorded-video business flow

The system SHALL expose uploaded assets through the original UI same-origin routes for semantic search, thumbnails, byte-range playback, selected-segment chat, and deletion without requiring NVIDIA runtime services.

#### Scenario: Search, playback and selected-segment understanding succeed

- **GIVEN** a recovered job has completed `publish` with real vision and embedding provider checkpoints
- **WHEN** its case query is submitted through the original UI same-origin search route
- **THEN** the result binds the expected `asset_id`, `job_id`, and `segment_id`
- **AND** its thumbnail is non-empty and a one-byte media request returns HTTP 206 with valid Range headers
- **AND** the original UI `+ Chat` context resolves the same server-owned asset and segment
- **AND** the chat trace contains `original_ui.chat.request` and `video_understanding.result`
- **AND** the answer is non-empty and does not contain an error response

#### Scenario: Completed acceptance assets are deleted idempotently

- **WHEN** the acceptance runner deletes each of its three completed assets twice through the original UI same-origin route
- **THEN** both deletion attempts complete without creating duplicate work
- **AND** Elasticsearch contains no matching documents
- **AND** SQLite contains a deletion tombstone but no job, job-step, or segment rows for the asset
- **AND** source, derived, thumbnail, and media paths are no longer accessible

### Requirement: Auditable production acceptance

The project SHALL provide one no-sudo Ubuntu command that performs the two-run, three-video production business-flow acceptance and writes atomic Chinese evidence.

#### Scenario: Production acceptance reports PASS only with complete evidence

- **WHEN** `scripts/recorded-video-production-acceptance.py` reports PASS
- **THEN** the report names two distinct launcher run IDs, three unique asset/job identities, concurrency 3, Worker restart PASS, provider models, Elasticsearch segment counts, search identity, HTTP 206, selected-video understanding, and deletion cleanup
- **AND** a case JSON file records evidence for all three videos
- **AND** referenced logs contain no API key or Authorization value
- **AND** any missing dependency, malformed evidence, provider failure, search miss, chat failure, or cleanup failure produces a non-zero exit and a FAIL report
