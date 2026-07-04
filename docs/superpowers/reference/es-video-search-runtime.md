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

## Mapped Server Copy

`Z:\vsa-agent` is the mapped server project copy. After local commits, sync the
changed files there. If commands cannot execute through the mapped drive,
validation is blocked until a server shell is available; the scripts are still
copied so the server can run the same commands.
