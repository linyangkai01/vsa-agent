# Elasticsearch Ingest Runtime Validation

## Purpose

Use this opt-in smoke check to prove that a running `/api/search/ingest` service writes a normalized video document to a real Elasticsearch index.

This validation is not part of the default unit test suite. It requires a reachable API service and Elasticsearch endpoint.

## Prerequisites

- Elasticsearch is running and reachable from the machine that runs the smoke script.
- The API service is running with search ingest enabled through a temporary config file.
- Python dependencies are installed for the project, including `elasticsearch`.
- The target index can be created or written by the configured Elasticsearch user.

## Temporary Config

Keep the repository default `config.yaml` with `search.enabled: false`. For runtime validation, create a temporary config outside the committed default, for example `tmp/es-runtime-config.yaml`:

```yaml
search:
  enabled: true
  es_endpoint: "http://127.0.0.1:9200"
  embed_index: vsa-video-embeddings
  request_timeout_sec: 30.0
  verify_certs: true
```

If the endpoint uses a self-signed TLS certificate, keep the temporary config explicit and pass `--insecure` to the smoke script only for that validation run.

## Start The API

Point `VSA_CONFIG` at the temporary config and start FastAPI:

```powershell
$env:VSA_CONFIG = "D:\WorkPlace\vsa-agent\tmp\es-runtime-config.yaml"
python -m uvicorn vsa_agent.api.routes:app --host 127.0.0.1 --port 8000
```

Leave this process running while the smoke script executes.

## Run The Smoke Check

From another shell:

```powershell
python scripts\es_ingest_smoke.py --api-url http://127.0.0.1:8000 --es-endpoint http://127.0.0.1:9200 --index vsa-video-embeddings
```

Environment variables can replace the flags:

```powershell
$env:VSA_API_URL = "http://127.0.0.1:8000"
$env:VSA_ES_ENDPOINT = "http://127.0.0.1:9200"
$env:VSA_ES_INDEX = "vsa-video-embeddings"
python scripts\es_ingest_smoke.py
```

Expected output:

```text
PASS: Elasticsearch ingest smoke validation
```

## Inspect Elasticsearch Manually

Refresh and inspect the runtime validation document:

```powershell
curl -X POST "http://127.0.0.1:9200/vsa-video-embeddings/_refresh"
curl "http://127.0.0.1:9200/vsa-video-embeddings/_search?q=video_id:runtime-video-*"
```

The indexed document should include:

- `video_id`
- `video_name`
- `description`
- `sensor_id`
- `start_time`
- `end_time`
- `screenshot_url`
- `vector`
- `metadata.site`

## Cleanup

Delete only the runtime validation documents when sharing an index:

```powershell
curl -X POST "http://127.0.0.1:9200/vsa-video-embeddings/_delete_by_query" -H "Content-Type: application/json" -d "{\"query\":{\"prefix\":{\"video_id\":\"runtime-video-\"}}}"
```

If the index was created only for the smoke check, deleting the whole test index is also acceptable:

```powershell
curl -X DELETE "http://127.0.0.1:9200/vsa-video-embeddings"
```

## Server Validation Notes

- Sync the committed branch to the server only when a server runtime environment is explicitly in use.
- Keep server credentials and temporary configs out of git.
- Run the same smoke command against the server API URL and Elasticsearch endpoint.
- Record the command, PASS output, and cleanup action in the development status or a dedicated validation report.
