# vss-business-flow-parity

## Why

`vsa-agent` is intended to replace the useful recorded-video business flows from NVIDIA VSS without requiring NVIDIA runtime services. The current project can run real-video shared and graph validations, but still needs a scoped parity milestone for graph acceptance, local archive search, validation gates, and documented live-run evidence.

## What Changes

- Define recorded-video VSS parity around Q&A, long-video understanding, report generation, graph-mode TopAgent tool selection, local archive search, and replayable validation.
- Add local archive search acceptance independent of NVIDIA services.
- Promote live-run validator metrics and repeated-LVS checks into acceptance criteria.
- Keep report quality, Enterprise RAG, real-time alerts, UI, production deployment, and full VST/VIOS parity out of this change.

## Impact

- Affects live-video validation, search acceptance tests, validator behavior, and project documentation.
- Does not add required NVIDIA dependencies.
