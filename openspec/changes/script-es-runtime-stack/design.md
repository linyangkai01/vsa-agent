## Context

The project already has the lower-level pieces for Elasticsearch video segment
validation:

- `docker-compose.es.yml` defines a single-node development Elasticsearch
  service.
- `scripts/es-dev-start.ps1`, `scripts/es-dev-stop.ps1`, and
  `scripts/es-dev-probe.ps1` start, stop, and probe Elasticsearch.
- `scripts/es_ingest_smoke.py` posts a representative video segment record to
  `/api/search/ingest`, verifies the indexed document, and checks keyword
  retrieval from the configured ES index.
- `vsa_agent.api.routes:app` exposes `/health` and registers
  `/api/search/ingest`.

What is missing is the operator-facing wrapper that turns those pieces into a
single repeatable validation loop. The default committed `config.yaml` must stay
safe with `search.enabled: false`, so any stack validation must use a temporary
config file passed via `VSA_CONFIG`.

## Goals / Non-Goals

**Goals:**

- Provide a one-command runtime validation path that starts Elasticsearch,
  starts FastAPI with search enabled through a temporary config, runs the smoke
  script, and reports PASS/FAIL.
- Provide stop/cleanup behavior for the API process, temporary config, and ES
  container.
- Make the same commands usable from the mapped server project at
  `Z:\vsa-agent`.
- Preserve normal unit tests without requiring a running Elasticsearch service.
- Provide an interactive mode that starts ES, the API, and original UI together
  and retains them for browser-driven validation.
- Connect the original UI's existing `/api/v1/search` contract to the existing
  SearchAgent and ES-backed `embed_search` tool path.

**Non-Goals:**

- Do not enable Elasticsearch in the committed default `config.yaml`.
- Do not implement NVIDIA VSS Kafka, Logstash, VST, or MDX services.
- Do not store video bytes in Elasticsearch.
- Do not add production cluster management, index lifecycle policies, or secure
  multi-node ES deployment.

## Decisions

1. Add a stack-level PowerShell script rather than expanding the Python smoke
   script into a service manager.

   PowerShell already owns the local ES lifecycle scripts, and it can manage
   Windows-local process startup, environment variables, health polling, and
   cleanup more naturally than the smoke script. The Python smoke script remains
   focused on validating API/ES behavior once services exist.

2. Generate a temporary config file for validation.

   The wrapper should copy or synthesize only the required runtime override:
   `search.enabled: true`, `search.es_endpoint`, `search.embed_index`, and
   `search.verify_certs: false` for the local insecure development ES. It will
   set `VSA_CONFIG` for the API process only, leaving `config.yaml` unchanged.

3. Treat Docker and API startup as explicit preflight checks.

   The script should fail with clear messages when Docker Compose, Uvicorn, the
   Python environment, or the configured ports are unavailable. A failed
   preflight is not a product failure; it is an environment blocker to report.

4. Keep cleanup conservative.

   The stack script should track the API process it starts and stop only that
   process. The ES stop script should continue to use `docker compose -f
   docker-compose.es.yml down`, matching the existing ES runtime ownership.

5. Reuse the original search contract rather than add a validation-only UI.

   The original VSS Search component already submits `POST
   ${NEXT_PUBLIC_AGENT_API_URL_BASE}/search` and renders `{data: SearchResult[]}`.
   The project will provide that route through its existing API prefix, adapt
   the request to `SearchInput`, and call the existing search-agent/tool stack.
   This retains one business flow from browser input through ES retrieval.

6. Treat selected ports as deliberate process-ownership boundaries.

   The interactive launcher will reclaim only the configured API, UI, and ES
   ports. It logs PID and command-line evidence before termination, waits for
   the release, and fails before startup if the release does not complete.

7. Make fast validation vector generation deterministic.

   The temporary stack config will set `search.force_mock_embedding: true`.
   This makes the ingest smoke record and the browser-originated query use the
   same deterministic mock vector even when the baseline configuration has a
   real embedding service. The flag defaults to false, so it does not alter
   production-style runtime behavior.

## Risks / Trade-offs

- Docker may be unavailable locally or through the mapped drive -> the script
  will report a clear blocker and docs will state that server-side execution is
  required for real validation.
- API startup may load user secrets or model config through the baseline config
  -> the temporary config should override only search settings and avoid
  changing model/backend defaults.
- Port collisions can make validation flaky -> scripts should expose API and ES
  port parameters and print the chosen endpoints.
- Background processes can linger after failures -> wrapper cleanup must run in
  `finally`-style logic and docs must include the stop command.
- A requested port could belong to an unrelated service -> reclamation is
  limited to the explicit target ports, is recorded in logs, and is opt-out
  configurable rather than scanning or killing arbitrary processes.

## Migration Plan

No data migration is required. After implementation, sync the new scripts and
documentation to `Z:\vsa-agent`, run the stack validation if the server-side
execution environment has Docker and Python dependencies, and record any
environment blocker in the verification report.

## Open Questions

No product decisions remain open. Runtime validation may still be blocked by
machine-level dependencies such as Docker availability, but that should be
handled as verification evidence rather than a design blocker.
