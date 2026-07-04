## 1. Search Retrieval Design

- [x] 1.1 Confirm the ES retrieval target is the existing `embed_search_tool` path.
- [x] 1.2 Decide vector-first behavior and keyword fallback boundaries.
- [x] 1.3 Define the lightweight video segment record contract and its boundary from original VSS `mdx-*` indices.
- [x] 1.4 Define server/runtime startup scope for the mapped `Z:\vsa-agent` project.

## 2. Elasticsearch Retrieval Implementation

- [x] 2.1 Add failing unit tests proving ES embed search returns an ingested video-segment-shaped hit.
- [x] 2.2 Add failing unit tests proving ES query failures preserve fallback behavior.
- [x] 2.3 Implement the minimal ES retrieval changes needed for those tests.
- [x] 2.4 Run focused search tests.

## 3. Scriptable ES Runtime

- [ ] 3.1 Add Docker Compose configuration for single-node development Elasticsearch.
- [ ] 3.2 Add start/stop/probe scripts for the ES development service.
- [x] 3.3 Add a runtime search validation script or command that ingests and then searches for a sample document.
- [ ] 3.4 Document local and mapped-server usage.

## 4. Server Sync And Validation

- [ ] 4.1 Sync completed files to `Z:\vsa-agent`.
- [ ] 4.2 Attempt server-side ES startup validation from the available execution environment.
- [ ] 4.3 If startup cannot be executed through the mapped drive environment, record the missing execution dependency clearly.

## 5. Verification And Closeout

- [ ] 5.1 Run focused unit tests for ES search, ingest smoke helpers, and existing ingest API.
- [ ] 5.2 Run OpenSpec validation for `wire-es-search-retrieval`.
- [ ] 5.3 Run or document runtime ES/search validation result.
