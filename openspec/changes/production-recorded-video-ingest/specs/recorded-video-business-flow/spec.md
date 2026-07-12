## ADDED Requirements

### Requirement: Original UI compatible recorded-video upload
The system SHALL accept real recorded-video uploads from the original UI without requiring NVIDIA VST, and SHALL preserve the original three-step upload contract for MP4 and MKV files up to the configured size limit.

#### Scenario: Original UI completes a chunked upload
- **GIVEN** the recorded-video runtime is ready and the selected file satisfies configured type and size limits
- **WHEN** the original UI requests an upload URL, sends all nvstreamer chunks, and posts the completion callback
- **THEN** the system stores the assembled source file under a stable asset ID
- **AND** the final chunk response returns that asset ID as both the compatible sensor and stream identity
- **AND** the completion callback returns an asynchronous job ID and status URL

#### Scenario: Repeated chunks and completion are idempotent
- **WHEN** the browser retries an already accepted chunk or repeats the completion callback
- **THEN** the system validates and acknowledges the existing chunk or job
- **AND** it does not duplicate source bytes, processing jobs, or Elasticsearch segment documents

#### Scenario: Invalid upload is rejected before processing
- **WHEN** an upload exceeds the configured size, uses an unsupported type, contains an unsafe filename, or cannot be assembled consistently
- **THEN** the system returns a clear client error
- **AND** it does not create a processing job or publish a partial source asset

### Requirement: Durable asynchronous recorded-video processing
The system SHALL process uploaded videos in an independent Worker using persisted job state, leases, heartbeats, bounded retries, stage checkpoints, cancellation, and restart recovery.

#### Scenario: Worker completes the processing pipeline
- **WHEN** a Worker claims a queued recorded-video job
- **THEN** it performs media probing, segment planning, representative-frame extraction, VLM description, embedding generation, and Elasticsearch indexing
- **AND** the job API exposes the current stage and terminal result
- **AND** the asset becomes searchable only after all required stages succeed

#### Scenario: Worker restart recovers an in-flight job
- **GIVEN** a Worker stops while a job is running
- **WHEN** its lease expires and a Worker becomes available
- **THEN** the job is eligible for reclaim
- **AND** processing resumes from validated stage checkpoints without duplicating completed model work

#### Scenario: Transient provider failure is retried
- **WHEN** a configured model or Elasticsearch operation fails with a timeout, rate limit, network error, or retryable server error
- **THEN** the job enters retry wait with bounded exponential backoff
- **AND** the final error and attempt count remain visible through the job API and logs

#### Scenario: Permanent media failure is terminal
- **WHEN** the source file is corrupt, unsupported, missing a required runtime dependency, or produces an incompatible embedding dimension
- **THEN** the job becomes failed without claiming the asset is searchable
- **AND** the original source remains available for diagnosis, deletion, or explicit retry after correction

### Requirement: Replaceable recorded-video analysis stages
The system SHALL separate segmentation, vision description, embedding, asset storage, and job persistence behind explicit interfaces so that later algorithms or infrastructure can be introduced without changing the upload and search business contracts.

#### Scenario: Fixed-duration segmentation produces stable segments
- **WHEN** the first production pipeline processes a valid uploaded video
- **THEN** the configured fixed-duration Segmenter emits ordered segments with deterministic IDs and start/end offsets
- **AND** each segment receives a description, representative thumbnail, embedding metadata, and absolute display timestamps

#### Scenario: Pipeline records reproducibility metadata
- **WHEN** a processing stage writes a reusable output
- **THEN** the asset manifest records the pipeline version, segmenter configuration, provider model identifiers, prompt version, output checksums, and timestamps
- **AND** secrets are excluded from manifests and logs

### Requirement: Local recorded-video asset and media service
The system SHALL store source and derived recorded-video assets outside Elasticsearch and SHALL expose the original UI compatible list, thumbnail, and time-range playback behavior through same-origin HTTP APIs.

#### Scenario: Search result displays and plays the matching segment
- **GIVEN** a ready asset contains an indexed segment
- **WHEN** the original UI renders and opens that search result
- **THEN** it loads the segment thumbnail through the media facade
- **AND** it obtains a media URL compatible with the original VST URL lookup contract
- **AND** the media response supports HTTP Range and positions playback at the segment time range

#### Scenario: Browser-incompatible source receives a playback proxy
- **WHEN** media probing detects that the uploaded container or codecs cannot be played by the supported browser
- **THEN** the pipeline creates a browser-compatible MP4 proxy with ffmpeg
- **AND** search and playback continue to reference the stable asset ID rather than a physical path

#### Scenario: Asset deletion cleans all owned data
- **WHEN** the user deletes a ready or failed recorded-video asset
- **THEN** deletion removes or tombstones its Elasticsearch documents, derived files, source file, segments, jobs, and upload records in a retryable order
- **AND** repeating the delete operation is idempotent

### Requirement: Production Elasticsearch segment indexing
The system SHALL create and validate an explicit, versioned Elasticsearch mapping for recorded-video segment documents and SHALL use deterministic document IDs for idempotent indexing.

#### Scenario: New segment index uses an explicit mapping
- **WHEN** an operator bootstraps a recorded-video index for a configured embedding model
- **THEN** the mapping defines stable identity, timestamp, offset, description, thumbnail, model, pipeline, and dense-vector fields with the configured dimensions and cosine similarity
- **AND** the runtime exposes the index through a configured alias

#### Scenario: Existing incompatible index blocks readiness
- **WHEN** the configured index has a vector dimension or required field mapping incompatible with the active production configuration
- **THEN** startup readiness fails with a clear mapping error
- **AND** the runtime does not silently modify the index or write incompatible vectors

#### Scenario: Completed segment documents match the original search contract
- **WHEN** a recorded-video job completes indexing
- **THEN** each Elasticsearch document represents one video segment and includes stable asset, segment, sensor, filename, description, ISO timestamp, offset, screenshot, pipeline, model, and vector fields
- **AND** `/api/v1/search` returns the matching fields in the original UI `{data: [...]}` contract

### Requirement: Production recorded-video runtime operations
The project SHALL provide one user-facing script that starts and monitors Elasticsearch, FastAPI, the recorded-video Worker, and the original UI without requiring administrator privileges.

#### Scenario: Runtime doctor detects blockers before partial startup
- **WHEN** required Python or Node dependencies, Docker Compose, ffprobe/ffmpeg, data-directory permissions, disk capacity, model configuration, ports, or Elasticsearch mapping are unavailable
- **THEN** the launcher identifies the failing component and remediation context
- **AND** it does not report the production stack as ready
- **AND** it never attempts sudo or terminates a listener owned by another user

#### Scenario: Single-port SSH tunnel reaches the business flow
- **GIVEN** all services bind to loopback on the server
- **WHEN** a user forwards only the original UI port over SSH
- **THEN** the browser reaches upload, task, search, thumbnail, and Range media APIs through the UI same-origin proxy
- **AND** the API and Elasticsearch ports do not need to be exposed to the browser network

#### Scenario: Runtime preserves complete component logs
- **WHEN** the stack starts
- **THEN** it creates a unique run directory containing stack, API, Worker, UI, Elasticsearch, and process-manifest logs
- **AND** terminal output prefixes component log lines
- **AND** request, asset, job, stage, and attempt identifiers allow one business flow to be traced without logging credentials or video contents

#### Scenario: Default runtime startup does not pollute production data
- **WHEN** the user starts the normal interactive stack
- **THEN** startup performs non-mutating readiness checks and does not write a smoke video into the production alias
- **AND** an explicit validation mode uses isolated validation data and removes it after completion

### Requirement: Recorded-video production acceptance
The system SHALL provide automated and server-side validation for concurrency, recovery, failure handling, original UI compatibility, semantic retrieval, media playback, and lifecycle cleanup.

#### Scenario: Three uploaded videos complete without duplicate segments
- **WHEN** the original UI submits three valid recorded videos concurrently within configured limits
- **THEN** all jobs reach completed
- **AND** Elasticsearch contains exactly one document per expected deterministic segment ID

#### Scenario: End-to-end original UI flow succeeds
- **WHEN** a user uploads a representative MP4 or MKV, waits for processing, and searches for known visual content
- **THEN** the original UI returns the correct video and time segment with a visible thumbnail
- **AND** opening the result produces a successful HTTP 206 media response and playable content at the matching range

#### Scenario: Server validation records diagnosable evidence
- **WHEN** the production recorded-video validation is run in the approved Ubuntu server environment
- **THEN** the report records runtime configuration without secrets, component readiness, job stage history, model and Elasticsearch call outcomes, search result identity, media response checks, and cleanup results
- **AND** a failed dependency or quality assertion is reported as a failure rather than a pass or silent skip

## MODIFIED Requirements

### Requirement: Elasticsearch video segment search retrieval

The system SHALL search recorded-video segment index records from Elasticsearch when search indexing is enabled and records have been written to the configured embed index.

The indexed Elasticsearch records SHALL represent searchable video segments, not stored video files and not Enterprise RAG knowledge-base documents.

#### Scenario: Embed search returns an ingested Elasticsearch video segment record

- **GIVEN** `search.enabled` is true, `search.es_endpoint` is set, and `search.embed_index` contains a video segment record written by an approved ingest path
- **WHEN** the project runs an embed-only recorded-video search whose query matches that record
- **THEN** the search returns a `SearchOutput` containing a `SearchResult` for the indexed video segment record
- **AND** the result includes video name, description, timestamps, sensor id, screenshot URL, and similarity

#### Scenario: Ingested record preserves video segment identity

- **GIVEN** an approved ingest path receives metadata containing video/source identity, description, timestamp range, vector, and screenshot URL fields
- **WHEN** it indexes the record into Elasticsearch
- **THEN** the indexed record contains stable top-level fields for `video_id`, `video_name`, `description`, `sensor_id`, `start_time`, `end_time`, `screenshot_url`, and `vector`
- **AND** the original or normalized metadata is preserved for forward compatibility

#### Scenario: Video files remain outside Elasticsearch

- **GIVEN** a recorded video has been indexed for search
- **WHEN** a search result is returned from Elasticsearch
- **THEN** the result references the video segment by source id, timestamp range, and URL fields
- **AND** Elasticsearch is not treated as the storage location for the video bytes

#### Scenario: Enterprise RAG document knowledge is out of scope

- **WHEN** the recorded-video search path indexes or searches Elasticsearch
- **THEN** it only handles video segment search records
- **AND** it does not create or query SOP, manual, policy, or other Enterprise RAG document collections

#### Scenario: Development search may use explicit fallback

- **GIVEN** a development or test profile explicitly enables fallback behavior
- **WHEN** Elasticsearch retrieval is disabled or unavailable
- **THEN** the search path may use the configured in-memory or deterministic test implementation
- **AND** normal unit tests do not require a running Elasticsearch service

#### Scenario: Production semantic search fails closed

- **GIVEN** the production recorded-video profile disables mock fallback
- **WHEN** Elasticsearch is unavailable, query embedding fails, required credentials are missing, or the query vector is incompatible with the index
- **THEN** the search request returns a controlled error and logs the failing dependency
- **AND** it does not silently use deterministic mock embeddings or an in-memory store
