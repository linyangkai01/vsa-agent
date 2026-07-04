## 1. Runtime Validation Design

- [ ] 1.1 Identify the least invasive validation entry point for a real Elasticsearch ingest smoke test.
- [ ] 1.2 Decide whether the smoke path should be a Python script, pytest integration test, documentation-only command sequence, or a combination.

## 2. Implementation

- [x] 2.1 Add the selected runtime validation script or opt-in integration test for `/api/search/ingest`.
  - [x] 2.1.a Add helper-level smoke payload and validation tests.
  - [x] 2.1.b Add API POST, Elasticsearch lookup, and CLI execution path.
- [ ] 2.2 Add ES validation documentation with prerequisites, temporary config, API startup, sample payload, index verification, and cleanup steps.
- [ ] 2.3 Update the development status entry with the active change and validation command.

## 3. Verification And Closeout

- [ ] 3.1 Run focused unit tests covering the existing ingest endpoint.
- [ ] 3.2 Run OpenSpec validation for `verify-es-ingest-runtime`.
- [ ] 3.3 If a documented Elasticsearch server validation environment is available, sync code there and run the smoke validation; otherwise record the missing external dependency clearly.
