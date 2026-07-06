## MODIFIED Requirements

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
