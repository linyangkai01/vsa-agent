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

Use this to start Elasticsearch, FastAPI and the original VSS UI together. The
default interactive mode writes a sample record, verifies `/api/v1/search`, and
keeps the stack running for browser validation. It reclaims only the selected
API/UI ports before startup. Elasticsearch remains Docker Compose-owned so the
launcher does not kill Docker's port proxy; an ES startup failure prints the
last container logs instead.

On Windows PowerShell:

```powershell
.\scripts\es-runtime-stack.ps1 -ApiPort 8000 -EsPort 9200 -UiPort 3000 -Index vsa-video-embeddings
```

On Linux/Ubuntu bash:

```bash
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings
```

Expected success output includes:

```text
PASS: ES runtime stack validation succeeded
  api: http://127.0.0.1:8000
  es:  http://127.0.0.1:9200
  index: vsa-video-embeddings
```

Open `http://127.0.0.1:3000`, switch to Search, and search for
`forklift near worker`. The result list must include `runtime-validation.mp4`.
Confirm `.runtime/es-stack/api.log` contains both `original_ui.search.request`
and `search_agent.embed_search`.

The script writes a temporary config under `.runtime\es-stack\config.yaml` and
passes it to the API process through `VSA_CONFIG`. The committed `config.yaml`
remains unchanged and keeps `search.enabled: false`. The temporary config sets
`search.force_mock_embedding: true` so smoke ingest and browser query use the
same deterministic vector; production configurations keep that flag disabled.

Elasticsearch data uses the Docker-managed named volume `vsa-agent-es-data` by
default. This avoids requiring write access or `sudo chown` on the project
directory. A user still needs permission to run Docker commands. To remove the
validation data intentionally, run `docker volume rm vsa-agent-es-data` after
stopping the stack.

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

## Ubuntu Server Preflight (No Administrator Permission Required)

The launcher uses files inside the repository, Docker access already available
to the current user, and the selected Conda environment. It never uses `sudo`.
Before the first run after synchronizing dependency declarations, install the
project dependencies into the same environment used by the launcher:

```bash
cd /data/project/lyk/vsa-agent
conda run -n vsa-agent python -m pip install --upgrade -e '.[dev]'
```

The launcher checks `aiohttp`, `elasticsearch[async]` version 8.14 through 8.x,
and `uvicorn` before starting Docker. If this check fails, run the command
above; the launcher will not claim that the stack started.

When Node.js is absent, interactive mode downloads the repository-pinned Node
runtime to `.deps/node` and installs original-UI dependencies without a system
package installation. Node bootstrap, package install, and UI failures are in
`.runtime/es-stack/ui.err.log`; FastAPI failures are in
`.runtime/es-stack/api.err.log`. The launcher tails the relevant log when a
child process exits before readiness.

For API/UI ports, the launcher logs the owning PID and command, sends `TERM`,
waits five seconds, then sends `KILL` only if the listener remains. If neither
`lsof` nor `fuser` is available, it fails before starting a partial stack. Port
9200 is intentionally left to Docker Compose: if another service owns it,
Docker's error and ES logs identify the conflict without killing an unrelated
Docker proxy.

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

The manifest includes the stack launcher, Node bootstrap helper, and original
UI runner together so the server does not execute stale startup dependencies.
