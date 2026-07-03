---
comet_change: wire-es-ingest
role: technical-design
canonical_spec: openspec
---

# Wire ES Ingest Design

Date: 2026-07-03

## Goal

Replace the mock `/api/search/ingest` response with a real, configuration-driven Elasticsearch ingest path for recorded-video search metadata.

## Current Context

The API module `src/vsa_agent/api/video_search_ingest.py` currently returns `indexed: true` without reading configuration or touching Elasticsearch. The repository already has `SearchBackendConfig` and ES-backed search tools, so ingest should use the same `search` block instead of adding another configuration surface.

The FastAPI app in `src/vsa_agent/api/routes.py` registers other API routers manually by extending `app.router.routes`; the ingest router should follow that local pattern.

## Design

Add typed request and response models around `POST /api/search/ingest`.

The request body accepts:

- `video_id`: required string.
- `metadata`: optional JSON object, defaulting to an empty object.

The endpoint reads `get_config().search`.

If `search.enabled` is false or `search.es_endpoint` is blank, the endpoint returns:

```json
{
  "status": "skipped",
  "video_id": "<video_id>",
  "indexed": false
}
```

No Elasticsearch client is created in the skipped path.

If search is enabled, the endpoint creates an `AsyncElasticsearch` client using `es_endpoint`, `request_timeout_sec`, and `verify_certs`. It indexes one normalized document into `search.embed_index` and returns `status: "ingested"`, `indexed: true`, and the Elasticsearch result id.

## Document Shape

The indexed document keeps the caller-provided metadata and promotes common video search fields to top-level keys:

- `video_id`
- `video_name`
- `description`
- `sensor_id`
- `start_time`
- `end_time`
- `screenshot_url`
- `vector`
- `metadata`

The endpoint does not generate embeddings. If the caller supplies a vector in metadata, it is preserved.

## Error Handling

If the Elasticsearch index call raises, the endpoint raises HTTP 502 with a concise detail message and does not claim indexing succeeded. Client cleanup is attempted in a `finally` block when a client was created.

## Testing

Unit tests cover:

- skipped behavior when search is disabled or has no endpoint;
- successful indexing through a fake `AsyncElasticsearch`;
- HTTP 502 on ES failure;
- route registration on the FastAPI app.

The focused verification set includes the new API tests plus existing original UI chat, config search, ES search tools, search tool, and search agent tests.
