---
comet_change: wire-es-search-retrieval
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-04-wire-es-search-retrieval
status: final
---

# Wire ES Search Retrieval Design

## Context

The original VSS project uses Elasticsearch for video retrieval, but ES does
not store video files directly. VST/nvstreamer owns the video bytes and returns
source identifiers such as `sensorId`. The search stack stores searchable video
segment index records in ES: source identity, timestamp range, text
description, vectors, object/frame metadata, and enough URL context to build
screenshots or clips.

This project already has a lighter shape:

- `POST /api/search/ingest` writes a normalized record to
  `search.embed_index` when `search.enabled` and `search.es_endpoint` are set.
- The normalized record currently contains `video_id`, `video_name`,
  `description`, `sensor_id`, `start_time`, `end_time`, `screenshot_url`,
  `vector`, and raw `metadata`.
- `embed_search_tool` already tries Elasticsearch first via `_search_real_es`
  and falls back to the in-memory store when ES is disabled or unavailable.
- `search_tool` routes embed-only and fusion paths through the registered embed
  search behavior.

The confusion to avoid: an Elasticsearch document is a JSON index record. In
this change it represents a searchable video segment record, not a Word/PDF
knowledge-base document.

## Goals

- Make ES-backed recorded-video search retrieve records written by
  `/api/search/ingest`.
- Preserve the current lightweight project shape while aligning terminology and
  fields with the original VSS video-search model.
- Keep normal tests independent of a running ES service.
- Add a scriptable single-node development ES runtime and a repeatable
  ingest-then-search validation path.
- Keep Enterprise RAG document retrieval out of this change.

## Non-Goals

- Do not reproduce the full original VSS `mdx-*` Kafka/Redis/Logstash pipeline.
- Do not store MP4 bytes in Elasticsearch.
- Do not implement VST/nvstreamer, RTVI-CV, or RTVI-Embed services.
- Do not build Enterprise RAG document ingestion or `frag_retrieval`.
- Do not enable ES by default in committed `config.yaml`.

## Selected Approach

Use a hybrid compatibility path.

The implementation keeps the current `search.embed_index` and
`/api/search/ingest` contract as the first deliverable, but treats each indexed
record as a video segment. The code should avoid naming that implies a
general-purpose document knowledge base. The first search path is:

1. A caller posts a video segment record to `/api/search/ingest`.
2. The endpoint normalizes common metadata aliases into stable search fields.
3. The record is indexed into the configured ES embed index.
4. `embed_search_tool` generates a query embedding and searches that index.
5. Hits are mapped into `SearchResult` with video name, description,
   timestamps, sensor id, screenshot URL, and similarity.
6. If ES is disabled, the index is missing, ES rejects the query, or the
   embedding path cannot run, the existing fallback behavior remains intact.

This keeps the current project shippable while leaving a clean path to later
add VSS-style index families:

- `mdx-embed-filtered-*` for chunk-level video embeddings.
- `mdx-behavior-*` for object/behavior embeddings.
- `mdx-raw-*` or `mdx-frames-*` for frame/object metadata.

## Data Contract

The lightweight segment record should be treated as:

```json
{
  "video_id": "stable uploaded-video or source id",
  "video_name": "display filename or source name",
  "description": "searchable segment text",
  "sensor_id": "camera/source id when available",
  "start_time": "segment start timestamp",
  "end_time": "segment end timestamp",
  "screenshot_url": "client-facing image URL when available",
  "vector": [0.1, 0.2],
  "metadata": {}
}
```

`metadata` preserves the source payload for forward compatibility. Search
should read stable top-level fields first, then fall back to nested metadata
aliases only where existing ingest behavior already supports them.

## Query Behavior

The primary ES query remains vector-first. Query embedding generation uses the
project embedding client. ES retrieval should use the configured
`search.vector_field`, `search.embed_index`, and
`search.embed_confidence_threshold`.

Keyword fallback is allowed only as a conservative runtime validation and
resilience path. It should not silently mask vector misconfiguration when ES is
configured for semantic search. A warning should make fallback visible.

## Runtime Scripts

Add development-only ES runtime support:

- Single-node Docker Compose service.
- Configurable HTTP port, data path, and container name.
- Security disabled by default for local/server development only.
- Start, stop, and probe scripts.
- A validation script or documented command sequence that starts ES, ingests a
  sample video segment record, runs search, and checks that the expected result
  is returned.

The mapped server directory `Z:\vsa-agent` is a sync target. Runtime validation
there is valid only if commands can actually run against that environment. If a
mapped drive is available but no server-side execution channel exists, the
scripts should still be synced and the blocker should be stated plainly.

## Testing Strategy

- Unit test that an ES hit shaped like `/api/search/ingest` output maps to a
  `SearchOutput` result.
- Unit test that ES disabled, missing index, or rejected query preserves
  fallback behavior.
- Unit test that keyword fallback, if implemented, returns expected fields
  without requiring vector mappings.
- Focused ingest API tests for skipped and indexed cases using a mocked ES
  client.
- OpenSpec validation for `wire-es-search-retrieval`.
- Optional runtime validation with Docker/ES available locally or on the mapped
  server execution environment.

## Risks

- ES vector field mappings may not match the query style. Tests should cover
  the query body, hit mapping, and failure fallback.
- Mock embeddings can produce vectors with dimensions that differ from runtime
  mappings. Runtime scripts should make the expected vector dimension explicit
  when creating sample mappings or sample data.
- Terminology drift can reintroduce confusion between video segment index
  records and Enterprise RAG documents. Specs and docs should consistently say
  "video segment index record" for this change.
