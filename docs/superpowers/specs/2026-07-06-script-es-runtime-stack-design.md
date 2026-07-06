---
comet_change: script-es-runtime-stack
role: technical-design
canonical_spec: openspec
---

# Script ES Runtime Stack Design

## Context

The project already has the ES runtime pieces needed for video segment search
validation:

- `docker-compose.es.yml` defines the single-node development Elasticsearch
  service.
- `scripts/es-dev-start.ps1`, `scripts/es-dev-probe.ps1`, and
  `scripts/es-dev-stop.ps1` manage Elasticsearch directly.
- `scripts/es_ingest_smoke.py` validates the API and ES behavior once both
  services are reachable.
- `vsa_agent.api.routes:app` exposes `/health` and registers
  `/api/search/ingest`.

The missing piece is orchestration. Today a developer has to start ES, create a
temporary search-enabled config, start FastAPI, wait for health, run the smoke
script, then clean up. This change turns that into a single repeatable stack
validation path that can run locally or from the mapped server project copy at
`Z:\vsa-agent`.

## Goals

- Add a scriptable ES + FastAPI stack validation command.
- Keep committed `config.yaml` safe with `search.enabled: false`.
- Generate a temporary runtime config for validation and pass it through
  `VSA_CONFIG`.
- Start FastAPI with `uvicorn vsa_agent.api.routes:app`.
- Wait for both ES and API health before running smoke validation.
- Run `scripts/es_ingest_smoke.py` against the configured API URL and ES
  endpoint.
- Clean up the API process and temporary config owned by the stack script.
- Leave clear PASS/FAIL output and troubleshooting hints.

## Non-Goals

- Do not implement original NVIDIA VSS Kafka, Logstash, VST, or MDX services.
- Do not store video bytes in Elasticsearch.
- Do not enable Elasticsearch by default in committed config.
- Do not manage a production Elasticsearch cluster.
- Do not require Docker or Elasticsearch for normal unit tests.

## Selected Approach

Use a PowerShell stack-level orchestrator and keep the Python smoke script
focused on business validation.

The main script should be named `scripts/es-runtime-stack.ps1`. It owns the
validation sequence:

1. Resolve the repo root from the script location.
2. Start or reuse the development ES service through `scripts/es-dev-start.ps1`.
3. Write a temporary YAML config under `.runtime/es-stack/config.yaml`.
4. Start FastAPI in a child process with `VSA_CONFIG` pointing at that temp
   config.
5. Poll `http://127.0.0.1:<ApiPort>/health` until ready.
6. Invoke `python scripts/es_ingest_smoke.py` with the selected API URL, ES
   endpoint, index, and `--insecure`.
7. Print a concise PASS line with API URL, ES endpoint, and index.
8. In cleanup, stop only the API process started by the script. If requested,
   call `scripts/es-dev-stop.ps1` to stop ES.

This keeps responsibilities clean:

- PowerShell manages local/server process lifecycle.
- Docker Compose remains isolated in the existing ES lifecycle scripts.
- Python smoke validation continues to assert API and ES behavior.

## Runtime Config

The temporary config should preserve the existing baseline except for the
search section required by validation:

```yaml
search:
  enabled: true
  es_endpoint: http://127.0.0.1:9200
  embed_index: vsa-video-embeddings
  behavior_index: vsa-video-behavior
  frames_index:
  vector_field: vector
  embed_confidence_threshold: 0.0
  request_timeout_sec: 30.0
  verify_certs: false
  allow_mock_fallback: true
```

Implementation can either generate a full merged config or copy the committed
`config.yaml` and patch only the `search` section. The safer first
implementation is copy-and-patch because it preserves model, tool, server, and
profile settings without duplicating the whole config schema.

## Command Shape

The stack script should expose practical parameters:

```powershell
.\scripts\es-runtime-stack.ps1 `
  -ApiPort 8000 `
  -EsPort 9200 `
  -Index vsa-video-embeddings `
  -CondaEnv vsa-agent `
  -StopElasticsearch
```

Recommended defaults:

- `ApiPort`: `8000`
- `EsPort`: `9200`
- `Index`: `vsa-video-embeddings`
- `CondaEnv`: empty by default; when supplied, run Python/Uvicorn through
  `conda run -n <env>`.
- `StopElasticsearch`: false by default so a developer can keep ES warm across
  repeated validation runs.

## Error Handling

The script should fail early and plainly when prerequisites are missing:

- Docker Compose unavailable or ES does not become reachable.
- API port is already occupied.
- FastAPI process exits before `/health` becomes ready.
- `scripts/es_ingest_smoke.py` returns non-zero.

Cleanup should run after both success and failure. The script should stop the
API process it started and report the path to any retained temporary config or
log file.

## Testing Strategy

Normal unit tests should not start Docker or FastAPI. The first test layer
should cover script-adjacent behavior that is safe to run offline:

- Static checks that the stack script exists and references the expected
  lifecycle scripts and smoke script.
- If helpers are moved into Python or a small reusable module, unit-test
  temporary config generation and command construction.
- Existing `tests/unit/scripts/test_es_ingest_smoke.py` continues to protect the
  smoke validator.

Runtime verification is opt-in:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

Expected success output should include a clear PASS message and the endpoints
used. If Docker is unavailable on the current machine, verification should
record the exact blocker rather than claiming success.

## Server Sync

After local implementation and verification, sync the changed scripts, docs,
tests, and OpenSpec files to `Z:\vsa-agent`. The mapped drive can hold the
runnable files, but true runtime validation requires a server-side shell with
Docker and Python available. If only file mapping is available, record that as
the blocker.

## Risks

- Docker is not installed or cannot run in the current environment.
  Mitigation: preflight and clear blocker message.
- Port `8000` or `9200` is already occupied.
  Mitigation: expose `-ApiPort` and `-EsPort` parameters and print selected
  endpoints.
- API process may linger after smoke failure.
  Mitigation: track and stop only the process started by the stack script.
- Temporary config could be confused with committed config.
  Mitigation: write under `.runtime/es-stack/`, set `VSA_CONFIG` only for the
  child API process, and document that `config.yaml` remains unchanged.
