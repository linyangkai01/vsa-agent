# Task 8.8 Report

## Summary
Implemented the Phase 8B1 critic semantic closure for search QA flow across the four assigned files.

## What changed
- Added a shared `should_apply_critic()` helper in `src/vsa_agent/tools/search.py`.
- Updated `execute_core_search()` to use the shared critic gate so critic runs only when:
  - `config.enable_critic` is true
  - `search_input.use_critic` is true
  - `critic_agent` is present
- Refactored `src/vsa_agent/agents/search_agent.py` so fusion-path critic handling no longer drifts from tool-layer semantics.
- Added `_run_search_critic()` and `_execute_search_with_metadata()` to centralize optional critic behavior and metadata capture.
- Kept `execute_search()` returning `SearchOutput` unchanged.
- Extended `execute_search_agent_flow()` to accept optional `config` and `critic_agent` injections and to return real critic metadata:
  - `critic_requested`
  - `critic_applied`
  - `critic_error`
- Ensured critic failures do not break the main search path; the original search result still returns.

## TDD notes
1. Added failing unit tests for:
   - skipping critic when `use_critic=False`
   - recording metadata when critic is applied
   - recording metadata when critic raises while preserving the main result
   - shared gate helper semantics in `tools/search.py`
2. Ran focused tests and observed failures in the expected critic-behavior areas.
3. Implemented the minimal behavior change.
4. Re-ran focused tests to green.

## Tests run
### Focused unit tests
`conda run --no-capture-output -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py -v`

Result: `20 passed`

### Narrow acceptance check
`conda run --no-capture-output -n vsa-agent python -m pytest tests/acceptance/test_search_flow.py -k "use_critic or critic" -v`

Result:
- `test_execute_search_calls_critic_only_when_requested_in_fusion_flow`: passed
- `test_execute_search_degrades_when_critic_fails_in_fusion_flow`: passed
- `test_execute_search_skips_critic_when_disabled_in_fusion_flow`: now XPASSes because the implementation already satisfies the previously xfailed expectation

## Concerns
- The acceptance file still contains a strict `xfail` for the disabled-critic fusion case. Since this task must not edit acceptance tests, the narrow acceptance run reports an `XPASS(strict)` failure even though the implementation behavior is now correct.
- `execute_search()` now defaults `enable_critic` from `search_input.use_critic` when no explicit config is supplied, to preserve the existing public acceptance expectation that requested critic verification still runs in fusion mode.


## Task 8.8 reviewer-fix follow-up
- Removed the implicit `SearchAgentConfig(enable_critic=search_input.use_critic)` path so default execution keeps `enable_critic=False` unless explicitly injected.
- Restored `execute_search()` to its pre-expansion public shape: `(search_input, model_adapter=None, embed_search=None, attribute_search=None) -> SearchOutput`.
- Kept critic metadata recording inside the internal flow via `_execute_search_with_metadata()` and `execute_search_agent_flow()`.
- Added regression coverage for the default no-config path to prove `use_critic=True` alone does not activate critic, even when a critic agent is discoverable.

### Reviewer-fix tests run
`conda run --no-capture-output -n vsa-agent python -m pytest tests/unit/agents/test_search_agent.py tests/unit/tools/test_search.py -v`

Result: `22 passed`
