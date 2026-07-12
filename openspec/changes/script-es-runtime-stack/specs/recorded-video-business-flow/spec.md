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
