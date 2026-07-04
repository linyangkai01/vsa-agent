## Why

The project can now ingest recorded-video search metadata into Elasticsearch, but the next search path must reliably read those indexed video segment records instead of stopping at mock or in-memory results. The user also needs a server-ready Elasticsearch runtime script so the feature can be started and validated from the mapped server project without manual ES setup.

## What Changes

- Wire the configured Elasticsearch embed search path so `search` / `embed_search` can return video segment records written by `/api/search/ingest`.
- Keep default development safe: `config.yaml` remains `search.enabled: false`, and normal unit tests do not require a running Elasticsearch service.
- Add scriptable Elasticsearch runtime support, including a local/server start script and Docker Compose configuration suitable for a single-node development ES service.
- Add validation commands that ingest a sample video segment record, search it through the project search tool, and document how to run the same flow from `Z:\vsa-agent`.
- Sync the completed work to the mapped server project and verify the server-side startup path when the implementation is ready.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `recorded-video-business-flow`: add Elasticsearch-backed recorded-video search retrieval and scriptable Elasticsearch runtime startup expectations.

## Impact

- Affected tools: `src/vsa_agent/tools/embed_search.py`, `src/vsa_agent/tools/search.py` only if routing changes are required.
- Affected runtime scripts: new or updated scripts under `scripts/`, plus a Docker Compose file for Elasticsearch.
- Affected docs: ES runtime/search setup and development status.
- Affected external system: Elasticsearch single-node development service.
- Affected validation: focused unit tests remain isolated from Elasticsearch; opt-in runtime validation requires Docker/Elasticsearch availability.
- Explicitly out of scope: full original VSS `mdx-*` pipeline replication and Enterprise RAG document knowledge retrieval.
