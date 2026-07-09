# ES Video Search Runtime

This runtime is for development validation of video segment index records. It
does not store video bytes and does not reproduce the original VSS
Kafka/Logstash pipeline.

## Local Start

```powershell
.\scripts\es-dev-start.ps1 -Port 9200
```

## Probe

```powershell
.\scripts\es-dev-probe.ps1 -Endpoint http://127.0.0.1:9200
```

## Stop

```powershell
.\scripts\es-dev-stop.ps1
```

## Ingest And Search Validation

Start the API with a local override that enables search:

```yaml
search:
  enabled: true
  es_endpoint: http://127.0.0.1:9200
  embed_index: vsa-video-embeddings
  verify_certs: false
```

Then run:

```powershell
python scripts\es_ingest_smoke.py --api-url http://127.0.0.1:8000 --es-endpoint http://127.0.0.1:9200 --insecure
```

The smoke script posts one sample video segment index record to
`/api/search/ingest`, verifies the record exists in Elasticsearch, then runs a
keyword search against the same index to prove the record is retrievable.

## One-Command Stack Validation

Use this when you want the project to start Elasticsearch, start FastAPI with a
temporary search-enabled config, and run ingest/search smoke validation.

On Windows PowerShell:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200 -Index vsa-video-embeddings
```

On Linux/Ubuntu bash:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --index vsa-video-embeddings
```

Expected success output includes:

```text
PASS: ES runtime stack validation succeeded
  api: http://127.0.0.1:8000
  es:  http://127.0.0.1:9200
  index: vsa-video-embeddings
```

The script writes a temporary config under `.runtime\es-stack\config.yaml` and
passes it to the API process through `VSA_CONFIG`. The committed `config.yaml`
remains unchanged and keeps `search.enabled: false`.

To stop Elasticsearch after validation, include:

```powershell
.\scripts\es-runtime-stack.ps1 -StopElasticsearch
```

or on Linux/Ubuntu:

```bash
./scripts/es-runtime-stack.sh --stop-elasticsearch
```

If the script reports Docker, port, Uvicorn, or smoke validation failures, treat
that output as the runtime blocker and do not report ES runtime validation as
successful.

## Mapped Server Copy

`Z:\vsa-agent` is the mapped server project copy. After local commits, sync the
changed files there. From the mapped server copy:

```powershell
cd Z:\vsa-agent
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200
```

From the Ubuntu server shell:

```bash
cd /data/project/lyk/vsa-agent
chmod +x ./scripts/es-runtime-stack.sh
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --index vsa-video-embeddings --stop-elasticsearch
```

`Z:\vsa-agent` must be executable from the current Windows session, or the Ubuntu
server shell must run from `/data/project/lyk/vsa-agent`. Docker/Python must be
available in the execution environment. File mapping alone is not proof that
commands are running on the remote server.

## Mapped-Drive Sync Strategy

This project syncs server code through the already-authenticated Windows mapped
drive at `Z:\vsa-agent`. Do not use Git as the normal server sync path for this
project when password secrecy is the concern.

Before copying files, run the mapped-drive preflight:

```powershell
.\scripts\sync-server-files.ps1 -PreflightOnly
```

Then sync the runtime stack manifest:

```powershell
.\scripts\sync-server-files.ps1
```

For a no-write preview:

```powershell
.\scripts\sync-server-files.ps1 -DryRun
```

The helper copies only an explicit manifest of files required for runtime stack
validation. It avoids full-tree scans, avoids recursive `robocopy /E`, and does
not request or store any server password. If the script reports `Access denied`,
run the same command from the normal Windows PowerShell session that owns the
`Z:` mapping, or reconnect the mapped drive with write access.
