---
comet_change: verify-es-ingest-runtime
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-04-verify-es-ingest-runtime
status: final
---

# Verify ES Ingest Runtime Design

## Context

`POST /api/search/ingest` already indexes caller-provided metadata through `AsyncElasticsearch.index` when `search.enabled` and `search.es_endpoint` are configured. Existing unit tests cover skip, success, failure, and route registration behavior with fake Elasticsearch clients.

The missing piece is runtime evidence: a repeatable way to run the API against a real Elasticsearch service, submit a representative ingest payload, and prove the document lands in the configured index. The project default configuration must remain safe, with `search.enabled: false`, so this validation path must be explicit and opt-in.

## Confirmed Approach

Create an opt-in runtime smoke validation path made of a small script plus documentation.

The script will accept an Elasticsearch endpoint and index name through CLI flags or environment variables. It will create a temporary config file that enables search, sets `search.es_endpoint`, sets `search.embed_index`, and keeps the rest of the app config inherited from the checked-in baseline where practical. The app under test will use that temporary config through `VSA_CONFIG`.

The smoke flow will:

1. Preflight the Elasticsearch endpoint.
2. Start or target the FastAPI app serving `vsa_agent.api.routes:app`.
3. POST a representative payload to `/api/search/ingest`.
4. Assert the response reports `status: ingested`, `indexed: true`, and a non-empty `result_id`.
5. Query Elasticsearch for the submitted `video_id`.
6. Assert the indexed document contains `video_id`, `video_name`, `description`, `sensor_id`, timestamps, screenshot URL, vector metadata, and original metadata.

The validation must be separate from normal unit tests. If Elasticsearch is unavailable, default tests still pass; the runtime smoke command fails clearly with the missing external dependency.

## Alternatives Considered

### Documentation-only command sequence

This is simplest, but it is easy for commands and expected output to drift. It also leaves too much room for manual interpretation.

### Pytest integration test requiring Elasticsearch

This fits test tooling, but it risks making routine test runs depend on external infrastructure unless carefully gated. It is useful later, but too heavy as the first runtime validation step.

### Recommended: opt-in script plus documentation

This gives a repeatable command and concrete assertions while keeping normal development fast and deterministic. Documentation remains the human-readable source for prerequisites, server usage, and troubleshooting.

## Files And Boundaries

- Add a smoke validation script under `scripts/` so it is discoverable with other project run/validation commands.
- Add ES validation documentation under `docs/` so runtime setup and server validation are easy to find.
- Update `docs/DEVELOPMENT_STATUS.md` with the active change and the validation command.
- Do not modify the default `config.yaml` to enable ES.
- Do not change the `/api/search/ingest` API contract unless the smoke test reveals a concrete defect.

## Test Strategy

- Keep focused unit coverage in `tests/unit/api/test_video_search_ingest.py`.
- Add unit coverage for the smoke script logic where it can be tested without a real Elasticsearch service, such as payload construction, config generation, and response/document validation helpers.
- Run the smoke script only when a real Elasticsearch endpoint is supplied.
- Run `npx openspec validate verify-es-ingest-runtime` before closeout.

## Risks And Mitigations

- Elasticsearch may not be available on every machine. The script will perform a preflight check and fail with a direct message naming the missing endpoint.
- Port conflicts may prevent starting the API service. The script or docs will support targeting an already running API URL, so users can manage service startup separately when needed.
- Temporary config can accidentally leak into normal runs. The script will write config to a temporary path and pass it via `VSA_CONFIG`, leaving checked-in defaults unchanged.
- ES document visibility can lag immediately after indexing. The script will refresh or retry the index lookup in a bounded way before declaring failure.

## Implementation Divergence

During build, the smoke path was kept narrower than the initial technical design to avoid hidden side effects in a runtime validation command. The committed script targets an already running FastAPI service, posts a representative ingest payload, refreshes and queries the configured Elasticsearch index, and validates the indexed document. Temporary config creation and API service startup are documented operational steps rather than script-owned behavior.

This still satisfies the OpenSpec requirement because the project now has a repeatable runtime validation path with exact config, startup, smoke command, expected output, inspection, and cleanup instructions. It also keeps the default `config.yaml` safe with `search.enabled: false` and avoids making normal unit tests depend on Elasticsearch.
