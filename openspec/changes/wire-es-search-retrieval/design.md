## Context

The current ES path has three pieces in different maturity states:

- `/api/search/ingest` writes normalized recorded-video metadata into `search.embed_index` when ES is enabled.
- `embed_search_tool` already has an ES search branch that builds a vector `script_score` query and maps ES hits into `SearchOutput`.
- Runtime validation can post a sample ingest payload and inspect the ES index, but there is no script-owned ES runtime and no end-to-end validation that the project search tool retrieves the ingested document.

The user has a mapped server project at `Z:\vsa-agent`. The project should produce scripts/configuration that can be synced there and used to start ES for development validation. A mapped drive is enough for file sync, but starting a server-side process still depends on a command execution path on that server.

## Goals / Non-Goals

**Goals:**

- Make ES-backed `embed_search_tool` retrieval work against documents written by `/api/search/ingest`.
- Preserve existing fallback behavior when ES is disabled, unreachable, or unavailable.
- Add scriptable single-node ES startup for development/server validation.
- Add a validation path that starts ES, ingests a sample document, runs the project search path, and confirms the ingested document can be found.
- Sync completed work to `Z:\vsa-agent` and validate as far as the mapped server environment permits.

**Non-Goals:**

- Build a production Elasticsearch cluster, authentication model, monitoring stack, or index lifecycle policy.
- Replace the current search agent or original UI flows.
- Require real ES for normal unit tests.
- Change the committed default `config.yaml` to enable ES.

## Decisions

### Use the existing embed search path first

The first implementation target is `embed_search_tool` because `search_tool` already routes embed-only and fusion searches through the registered `embed_search` tool. This keeps the change small and avoids adding another search API surface.

Alternative considered: add a new ES-specific search tool. Rejected for this phase because it would create a second route to the same indexed documents and increase agent routing ambiguity.

### Add keyword fallback only when vector search cannot run

The ingested documents include a `vector` field when callers provide it, so vector search should remain the primary path. However, runtime validation should still be usable when embeddings or ES vector mapping are not ready. The ES retrieval implementation can fall back to a conservative `multi_match` query over `description`, `video_name`, `sensor_id`, and metadata fields when query embedding generation fails or ES rejects the vector query.

Alternative considered: make keyword search the default. Rejected because the project intent is ES-backed semantic search, and keyword search should not hide vector configuration problems during real deployments.

### Provide Docker Compose for development ES

Add a small Compose file for a single-node Elasticsearch service with persistent local data and security disabled by default for development validation. Provide scripts that start, stop, and probe the service. The scripts should keep ports and data paths configurable through environment variables.

Alternative considered: install Elasticsearch directly on the server. Rejected because it is harder to reproduce and clean up.

### Treat `Z:\vsa-agent` as sync target, not proof of remote execution

The local agent can copy files into `Z:\vsa-agent`, but a mapped drive alone does not prove that commands run on the remote server. Implementation should detect what is possible:

- If Docker/Compose can be invoked in the current environment against `Z:\vsa-agent`, run the startup validation there.
- If not, sync the scripts/configuration and record the missing execution channel clearly.

## Risks / Trade-offs

- ES vector mappings may not accept `script_score` over a plain numeric list -> use focused tests and add a keyword fallback for validation.
- Docker may not be installed or available from the mapped server environment -> scripts and docs remain useful, but server process validation may be blocked until an execution channel is available.
- Security-disabled ES is inappropriate for public networks -> make the scripts clearly development-only and configurable.
- Search can silently fall back to empty in-memory results -> tests should prove ES hits are returned when ES is configured and fake ES returns hits.

## Migration Plan

1. Add OpenSpec artifacts and technical design.
2. Add tests for ES retrieval behavior and fallback behavior.
3. Implement the minimum search changes.
4. Add ES runtime scripts and docs.
5. Validate locally with unit tests and OpenSpec.
6. Sync the committed files to `Z:\vsa-agent`.
7. Run server startup/search validation when a command execution path is available; otherwise record the blocker.

## Open Questions

- Is Docker Compose available from the environment that controls the mapped server project?
- Should the development ES service bind only to localhost, or should it bind to the server LAN interface for browser/API access from other machines?
