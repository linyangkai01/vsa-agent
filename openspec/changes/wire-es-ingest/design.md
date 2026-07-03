## Context

The original UI debug branch already has real Elasticsearch read paths in `embed_search` and `attribute_search`, controlled by `SearchBackendConfig`. The ingest endpoint remains a mock that always returns `indexed: true`, so callers cannot tell whether a video search record was actually written to the configured search backend.

## Goals / Non-Goals

**Goals:**

- Keep the existing `POST /api/search/ingest` route shape available.
- Use the existing `search` configuration block instead of adding another configuration surface.
- Write one caller-provided metadata document to `search.embed_index` when Elasticsearch search is enabled.
- Return explicit skipped and failure responses instead of mock success.
- Cover behavior with unit tests that use a fake Elasticsearch client.

**Non-Goals:**

- Generate embeddings from video or text.
- Upload video files or manage object storage.
- Emulate NVIDIA VST, S3, MinIO, or full video-management APIs.
- Change the existing Elasticsearch search query behavior.

## Decisions

### Decision: Use the existing `SearchBackendConfig`

`video_search_ingest` will call `get_config().search` and use `enabled`, `es_endpoint`, `embed_index`, `request_timeout_sec`, and `verify_certs`. This keeps ingest aligned with the ES search tools and avoids another source of truth.

Alternative considered: add endpoint-specific config. Rejected because ingest and search should point at the same ES deployment in this phase.

### Decision: Accept metadata as a JSON object and normalize a small document

The endpoint will accept `video_id` plus optional metadata. It will preserve metadata fields while normalizing common fields used by existing search result processing: `video_name`, `description`, `sensor_id`, `start_time`, `end_time`, `screenshot_url`, and `vector`.

Alternative considered: define a large strict schema. Rejected because the original UI/debug callers may send partial metadata, and this change only needs a reliable ingestion boundary.

### Decision: Treat disabled ES as skipped, not success

When `search.enabled` is false or `es_endpoint` is empty, the endpoint returns `status: "skipped"` and `indexed: false`. This makes local development safe while avoiding misleading success responses.

### Decision: Surface ES failures as HTTP 502

If the ES client raises during indexing, the API returns HTTP 502 with a concise message. This makes backend/search setup problems visible during browser debugging.

## Risks / Trade-offs

- Partial metadata may not be useful for semantic search until a vector is supplied. Mitigation: preserve supplied metadata and document that embedding generation remains out of scope.
- Index mappings may differ across deployments. Mitigation: use a flat, conservative document shape and preserve original metadata for downstream consumers.
- Full unit suite is currently blocked in this Windows environment by pytest temp/artifact permissions. Mitigation: verify the focused API and ES test set for this change and record the broader environment blocker in verification.
