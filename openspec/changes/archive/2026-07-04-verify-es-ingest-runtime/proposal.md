## Why

The Elasticsearch ingest endpoint is covered by unit tests, but the project does not yet have a repeatable way to verify it against a real Elasticsearch runtime. This change closes that gap so future ES work can be validated with concrete server-side evidence instead of mocks only.

## What Changes

- Add a repeatable runtime validation path for `/api/search/ingest` with a real Elasticsearch service.
- Document the required configuration, service startup assumptions, sample ingest payload, expected response, and index verification commands.
- Add focused automation where practical so the runtime smoke path can be run locally or on the documented validation server.
- Keep the current `/api/search/ingest` API contract unchanged unless validation reveals a defect.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `recorded-video-business-flow`: add runtime validation expectations for Elasticsearch video search ingest.

## Impact

- Affected API: `POST /api/search/ingest`.
- Affected configuration: `search.enabled`, `search.es_endpoint`, `search.embed_index`, `search.request_timeout_sec`, and `search.verify_certs`.
- Affected documentation: ES setup and validation instructions.
- Affected tests or scripts: focused smoke validation around real Elasticsearch ingest.
