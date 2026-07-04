## ADDED Requirements

### Requirement: Elasticsearch video search retrieval

The system SHALL search recorded-video metadata from Elasticsearch when search indexing is enabled and documents have been written to the configured embed index.

#### Scenario: Embed search returns an ingested Elasticsearch document

- **GIVEN** `search.enabled` is true, `search.es_endpoint` is set, and `search.embed_index` contains a document written by `/api/search/ingest`
- **WHEN** the project runs an embed-only recorded-video search whose query matches that document
- **THEN** the search returns a `SearchOutput` containing a `SearchResult` for the indexed document
- **AND** the result includes video name, description, timestamps, sensor id, screenshot URL, and similarity

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
