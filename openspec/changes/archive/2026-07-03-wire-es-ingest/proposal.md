## Why

`/api/search/ingest` still returns a mock success response even though the branch already has config-driven Elasticsearch search paths. This leaves the original UI and external callers without a trustworthy API for submitting video search records into the configured ES index.

## What Changes

- Replace the mock ingest response with config-driven behavior.
- Return a skipped response when Elasticsearch search is disabled or missing an endpoint.
- Index validated video metadata into `search.embed_index` when Elasticsearch search is enabled.
- Surface Elasticsearch indexing failures as clear API errors instead of pretending the record was indexed.
- Register the ingest router in the FastAPI app so `/api/search/ingest` is available in the debug stack.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `recorded-video-business-flow`: The recorded-video API surface gains a real Elasticsearch-backed search ingest path for video search metadata.

## Impact

- Affected API module: `src/vsa_agent/api/video_search_ingest.py`.
- Affected app wiring: `src/vsa_agent/api/routes.py`.
- Affected tests: `tests/unit/api/test_video_search_ingest.py` and route registration coverage.
- External system: Elasticsearch, using the existing `SearchBackendConfig` fields in `config.yaml`.
