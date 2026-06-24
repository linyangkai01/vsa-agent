# Evaluator Regression Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixture-driven evaluator regression entry for acceptance tests plus a default-skipped live API effect validation entry.

**Architecture:** Keep all fixture loading and dispatch logic on the test side so production code stays unchanged. Use one JSON fixture file for stable offline evaluator regression, and a separate live API acceptance test that only runs when explicit environment variables are present.

**Tech Stack:** Python 3.12, pytest, json, existing `evaluators/`, existing `UnderstandingResult` and `SearchOutput` models

## Global Constraints

- Do not introduce new runtime dependencies.
- Keep offline regression deterministic and cheap.
- Keep live API validation opt-in via environment variables.
- Do not move existing acceptance tests into a new framework.

---

## File Structure

**Create**
- `tests/acceptance/fixtures/evaluator_regression.json`
  - Small offline fixture corpus for understanding/search/report evaluation.
- `tests/acceptance/test_evaluator_regression.py`
  - Fixture loader, evaluator dispatch, and offline regression assertions.
- `tests/acceptance/test_evaluator_live_api.py`
  - Opt-in real model API effect validation entry.

**Modify**
- `docs/superpowers/vsa-agent-implementation-plan.md`
  - Record that evaluator regression and live API entry now exist.

### Task 1: Add the offline evaluator fixture corpus

**Files:**
- Create: `tests/acceptance/fixtures/evaluator_regression.json`
- Test: `tests/acceptance/test_evaluator_regression.py`

**Interfaces:**
- Produces: JSON fixtures with `name`, `evaluator_type`, `actual`, `expected`, and optional `min_score`

- [ ] **Step 1: Write the failing test**

```python
def test_load_regression_cases_returns_three_cases():
    from tests.acceptance.test_evaluator_regression import load_regression_cases

    cases = load_regression_cases()

    assert len(cases) == 3
    assert {case["evaluator_type"] for case in cases} == {"understanding", "search", "report"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py::test_load_regression_cases_returns_three_cases -v`
Expected: FAIL with missing module or missing fixture file

- [ ] **Step 3: Write minimal fixture file**

```json
[
  {
    "name": "understanding-basic",
    "evaluator_type": "understanding",
    "actual": {
      "query": "what happened",
      "source_type": "video_file",
      "summary_text": "person enters loading area and stops near forklift",
      "chunks": [],
      "events": [
        {
          "event_id": "event-1",
          "label": "loading area",
          "description": "person stops near forklift",
          "start_timestamp": "2026-06-19T10:00:00",
          "end_timestamp": "2026-06-19T10:00:10",
          "actors": [],
          "objects": [],
          "evidence": [
            {
              "source_type": "video_file",
              "video_path": "clip.mp4",
              "frame_indices": [],
              "frame_timestamps": []
            }
          ]
        }
      ],
      "metadata": {}
    },
    "expected": {
      "summary_terms": ["person", "forklift"],
      "events": [
        {
          "label": "loading area",
          "description_terms": ["stops"]
        }
      ]
    },
    "min_score": 1.0
  }
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py::test_load_regression_cases_returns_three_cases -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/fixtures/evaluator_regression.json tests/acceptance/test_evaluator_regression.py
git commit -m "test: add evaluator regression fixtures"
```

### Task 2: Add offline evaluator regression dispatch

**Files:**
- Create: `tests/acceptance/test_evaluator_regression.py`

**Interfaces:**
- Consumes: fixture JSON, `evaluate_understanding_result()`, `evaluate_search_output()`, `evaluate_report_markdown()`
- Produces: `load_regression_cases()`, `_evaluate_case(case)`, parameterized regression test

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.parametrize("case_name", ["understanding-basic", "search-basic", "report-basic"])
def test_regression_case_passes(case_name):
    from tests.acceptance.test_evaluator_regression import evaluate_case_by_name

    result = evaluate_case_by_name(case_name)

    assert result.passed is True
    assert result.score >= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py -v`
Expected: FAIL because loader/dispatch is not implemented yet

- [ ] **Step 3: Write minimal implementation**

```python
def load_regression_cases() -> list[dict]:
    ...


def evaluate_case(case: dict):
    if case["evaluator_type"] == "understanding":
        ...
    elif case["evaluator_type"] == "search":
        ...
    elif case["evaluator_type"] == "report":
        ...
    else:
        raise ValueError(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_evaluator_regression.py
git commit -m "test: add offline evaluator regression entry"
```

### Task 3: Add opt-in live API validation entry

**Files:**
- Create: `tests/acceptance/test_evaluator_live_api.py`

**Interfaces:**
- Consumes: explicit environment variables, existing `summarize_understanding_result()`, `evaluate_understanding_result()`
- Produces: one live API acceptance test that skips by default

- [ ] **Step 1: Write the failing test**

```python
def test_live_api_validation_skips_without_required_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from tests.acceptance.test_evaluator_live_api import should_run_live_api_validation

    assert should_run_live_api_validation() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py::test_live_api_validation_skips_without_required_env -v`
Expected: FAIL with missing module

- [ ] **Step 3: Write minimal implementation**

```python
def should_run_live_api_validation() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.anyio
async def test_live_api_understanding_quality():
    if not should_run_live_api_validation():
        pytest.skip("OPENAI_API_KEY not configured for live API validation")
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py -v`
Expected: PASS with one executed helper test and the live API test skipped

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_evaluator_live_api.py
git commit -m "test: add opt-in live evaluator validation"
```

### Task 4: Regression run and plan sync

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

**Interfaces:**
- Consumes: offline regression entry and live API entry
- Produces: updated master-plan status note

- [ ] **Step 1: Run acceptance regression for the new entry points**

Run: `conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_regression.py tests/acceptance/test_evaluator_live_api.py -q`
Expected: PASS with offline cases green and live API test skipped when env is absent

- [ ] **Step 2: Update the master implementation plan status**

```markdown
- [x] 已补齐 `evaluators/` 最小确定性评估框架：`4 passed`
- [x] 已新增 evaluator fixture 回归入口与默认跳过的 live API 效果验证入口
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md tests/acceptance/fixtures/evaluator_regression.json tests/acceptance/test_evaluator_regression.py tests/acceptance/test_evaluator_live_api.py
git commit -m "test: add evaluator regression acceptance entry"
```

## Self-Review

- Spec coverage: includes stable offline regression plus opt-in live API validation.
- Placeholder scan: all tasks have concrete files, commands, and outputs.
- Type consistency: fixture fields map directly to current evaluator interfaces.
