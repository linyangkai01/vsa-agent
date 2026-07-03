## Context

The previous `wire-es-ingest` change implemented `POST /api/search/ingest` and unit-tested the indexing behavior with fake Elasticsearch clients. The next useful step is operational: prove the same endpoint works against a real Elasticsearch service and leave a clean validation path for future ES search work.

The project is single-developer and uses a local-first Git flow. Development should stay on a local branch, merge back to local `master` when complete, then push only `master`.

## Goals / Non-Goals

**Goals:**

- Provide a repeatable smoke validation for real Elasticsearch ingest.
- Document ES runtime setup, config values, sample payload, API call, index lookup, and expected output.
- Keep validation focused enough to run locally or on the documented project validation server.
- Preserve the existing ingest API contract unless validation exposes a concrete defect.

**Non-Goals:**

- Build a full Elasticsearch-backed search retrieval implementation.
- Add UI search workflows.
- Design index lifecycle management, mappings, migrations, or production cluster operations beyond what the smoke validation requires.
- Push feature branches or create PRs.

## Decisions

- Use a smoke-validation path instead of broad integration infrastructure first. This proves the endpoint works with real ES while avoiding a larger test harness before the project needs it.
- Prefer a small script plus documentation when possible. A script captures the repeatable mechanics; documentation explains prerequisites, configuration, and how to inspect results.
- Treat Elasticsearch availability as an explicit precondition. Automated unit tests should not require a running ES service by default; runtime validation should be opt-in and clearly documented.
- Keep `config.yaml` defaults safe. The default committed config keeps search disabled; validation instructions should show temporary local/server overrides rather than requiring global defaults to enable ES.

## Risks / Trade-offs

- Real ES availability can vary by developer machine or server -> mitigate with explicit preflight checks and clear skip/failure messages.
- Elasticsearch version differences can affect index behavior -> mitigate by using basic document indexing and get/search commands that are stable across supported 8.x style deployments.
- Validation scripts can become stale if API payload fields change -> mitigate by using the same representative payload in docs and tests, and by keeping the script close to the API contract.
