# Design

## Scope

This change validates the open recorded-video business flow:

1. Resolve config from `config.yaml` plus optional `config.local.yaml`.
2. Analyze a real local video through shared and graph modes.
3. Prove graph-mode TopAgent can select tools without duplicate long-video VLM calls.
4. Validate run evidence with `validate-run`.
5. Add local archive search acceptance with deterministic local data.

## Out Of Scope

- Report wording polish.
- Enterprise RAG.
- Real-time alerts.
- UI.
- Production deployment.
- Full NVIDIA VST/VIOS parity.

## Acceptance Gates

- Unit tests for validator, live runner, registry, and search pass.
- Shared Ubuntu run validates with PASS.
- Graph Ubuntu run validates with PASS and no repeated LVS warning.
- Local archive search acceptance passes without Elasticsearch or NVIDIA services.
- Project status document records run IDs and metrics.
