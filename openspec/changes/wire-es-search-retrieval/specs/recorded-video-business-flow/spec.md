## ADDED Requirements

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
