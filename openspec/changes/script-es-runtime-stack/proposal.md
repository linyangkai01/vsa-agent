## Why

The project now has Elasticsearch ingest and retrieval tests plus separate ES
start/probe scripts, but the operational path still requires several manual
steps. This change makes the runtime validation loop direct: start ES, start the
FastAPI API with a temporary search-enabled config, run the ingest-search smoke,
and stop the stack cleanly.

## What Changes

- Add a scriptable ES + FastAPI runtime stack path for local and mapped-server
  validation.
- Generate a temporary search-enabled config for runtime validation without
  changing the committed default `config.yaml`.
- Add health checks and clear PASS/FAIL output around Elasticsearch, FastAPI,
  and ingest-search smoke validation.
- Add stop/cleanup behavior so validation services do not linger after a run.
- Update documentation so `Z:\vsa-agent` can run the same commands after sync.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `recorded-video-business-flow`: extend the Elasticsearch runtime validation
  requirement from "an ingest/search smoke path exists" to "the project provides
  scriptable ES + API stack startup, smoke validation, and cleanup."

## Impact

- Affected scripts: ES lifecycle scripts and a new stack-level validation entry.
- Affected API runtime: `vsa_agent.api.routes:app` started through Uvicorn for
  validation.
- Affected configuration: temporary `VSA_CONFIG` file with `search.enabled`,
  `search.es_endpoint`, `search.embed_index`, and `search.verify_certs`.
- Affected documentation: ES runtime and server mapped-drive validation guide.
- Affected tests: focused script tests for generated config, command assembly,
  or validation preflight behavior.
