# Tech Debt Then Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining non-blocking warnings first, then push the validated `codex/vsa-agent-closure` branch.

**Architecture:** Treat warning cleanup and push/integration as two independent phases. Phase 1 performs the smallest safe code/config updates needed to remove warning noise without changing business behavior; Phase 2 verifies and pushes the prepared branch.

**Tech Stack:** Git, pytest, PowerShell, existing FastAPI test stack

## Global Constraints

- Do not mix new feature work into this plan.
- Preserve the existing three-commit branch history.
- Keep warning cleanup limited to non-blocking issues only.
- Stop and re-scope if warning cleanup requires dependency upgrades or behavioral changes.

---

## File Structure

**Create**
- `docs/superpowers/plans/2026-06-24-push-then-tech-debt.md`
  - Execution checklist for push and warning cleanup.

**Modify**
- `docs/superpowers/specs/2026-06-24-push-then-tech-debt-design.md`
  - Stage and commit the approved design before execution.
- Potentially `tests/...` or config files only if warning cleanup proves safe and minimal.

### Task 1: Inspect and close the remaining warnings

**Files:**
- Modify: `tests/acceptance/test_phase5_online_flow.py`, `pyproject.toml`, `.gitignore`
- Reference: `docs/superpowers/specs/2026-06-24-push-then-tech-debt-design.md`

**Interfaces:**
- Consumes: latest pytest warning output
- Produces: warning-free green test result with no business behavior change

- [x] **Step 1: Reproduce warning sources**

```powershell
python -m pytest tests/acceptance/test_phase5_online_flow.py -q -W default
```

- [x] **Step 2: Replace deprecated `TestClient` usage with `httpx` ASGI transport**

Result:
- `tests/acceptance/test_phase5_online_flow.py` switched to async `httpx.AsyncClient`
- deprecated `fastapi.testclient` path removed

- [x] **Step 3: Resolve cache warning safely**

Result:
- confirmed root cause is Windows permission failure inside `pytest` cacheprovider temp-dir creation
- disabled cacheprovider via `addopts = ["-p", "no:cacheprovider"]`
- kept local cache ignore patterns defensive in `.gitignore`

- [x] **Step 4: Re-run targeted and full verification**

Run:
- `python -m pytest tests/acceptance/test_phase5_online_flow.py -q -W error`
- `python -m pytest tests -q`

Expected / Actual:
- targeted acceptance test passes with warnings treated as errors
- full suite result: `431 passed, 2 skipped`

- [ ] **Step 5: Commit**

### Task 2: Verify and push the current branch

**Files:**
- Modify: none
- Reference: `docs/superpowers/specs/2026-06-24-push-then-tech-debt-design.md`

**Interfaces:**
- Consumes: current branch `codex/vsa-agent-closure`, clean working tree, existing upstream remote
- Produces: pushed remote branch ready for PR or later review

- [ ] **Step 1: Verify the working tree is clean**

```powershell
git status --short
git branch --show-current
```

- [x] **Step 2: Verify tests still pass before push**

Run: `python -m pytest tests -q`
Expected: `431 passed, 2 skipped`

- [ ] **Step 3: Push the branch**

```powershell
git push -u origin codex/vsa-agent-closure
```

- [ ] **Step 4: Verify upstream is set**

Run: `git rev-parse --abbrev-ref --symbolic-full-name '@{u}'`
Expected: `origin/codex/vsa-agent-closure`

- [ ] **Step 5: Commit**

```bash
# Commit warning cleanup and doc alignment before push.
```

## Self-Review

- Spec coverage: now matches actual execution order and current branch state.
- Placeholder scan: warning cleanup steps are concrete and already verified.
- Type consistency: no new runtime interfaces are introduced by this plan.
