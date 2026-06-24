# Evaluators Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal deterministic `evaluators/` subsystem that can score understanding outputs, search outputs, and generated reports against expected fixtures.

**Architecture:** Keep the first version intentionally small: shared score/result models live in one module, and each evaluation surface gets a focused deterministic evaluator module. Scoring avoids LLM-as-judge and instead compares exact/normalized text, event labels, time windows, and ordered search hits so the framework is cheap to run inside unit tests and future fixture-based regression checks.

**Tech Stack:** Python 3.12, Pydantic v2, existing `UnderstandingResult`/`SearchOutput`/report models, pytest

## Global Constraints

- Do not introduce new runtime dependencies.
- Keep evaluator APIs synchronous and deterministic.
- Accept both Pydantic models and plain dictionaries where existing tools already do.
- Prefer small reusable helpers over a generalized plugin framework.

---

## File Structure

**Create**
- `src/vsa_agent/evaluators/__init__.py`
  - Public exports for evaluator result/data models and top-level evaluator functions.
- `src/vsa_agent/evaluators/data_models.py`
  - Shared contracts for expected fixtures, metric rows, and evaluation summaries.
- `src/vsa_agent/evaluators/understanding_eval.py`
  - Deterministic scoring for `UnderstandingResult` summary/events coverage.
- `src/vsa_agent/evaluators/search_eval.py`
  - Deterministic scoring for `SearchOutput` hit ordering and field matching.
- `src/vsa_agent/evaluators/report_eval.py`
  - Deterministic scoring for generated markdown report content and required section checks.
- `tests/unit/evaluators/test_understanding_eval.py`
  - Unit tests for summary/event evaluation rules.
- `tests/unit/evaluators/test_search_eval.py`
  - Unit tests for search hit evaluation rules.
- `tests/unit/evaluators/test_report_eval.py`
  - Unit tests for report markdown evaluation rules.

**Modify**
- `docs/superpowers/vsa-agent-implementation-plan.md`
  - Remove `evaluators/` from the remaining gap table and mark the execution status.

### Task 1: Define shared evaluator contracts

**Files:**
- Create: `src/vsa_agent/evaluators/data_models.py`
- Create: `src/vsa_agent/evaluators/__init__.py`
- Test: `tests/unit/evaluators/test_understanding_eval.py`

**Interfaces:**
- Produces: `MetricScore`, `EvaluationResult`, `ExpectedEvent`, `ExpectedSearchHit`, `ExpectedReportSection`
- Produces: package exports for `evaluate_understanding_result`, `evaluate_search_output`, `evaluate_report_markdown`

- [ ] **Step 1: Write the failing test**

```python
from vsa_agent.evaluators.data_models import EvaluationResult
from vsa_agent.evaluators.data_models import MetricScore


def test_evaluation_result_computes_pass_flag_from_metric_scores():
    result = EvaluationResult(
        evaluator_name="demo",
        score=0.75,
        metrics=[
            MetricScore(name="summary", score=1.0, passed=True),
            MetricScore(name="events", score=0.5, passed=False),
        ],
    )

    assert result.passed is False
    assert result.metrics[0].name == "summary"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_understanding_eval.py::test_evaluation_result_computes_pass_flag_from_metric_scores -v`
Expected: FAIL with import error for `vsa_agent.evaluators`

- [ ] **Step 3: Write minimal implementation**

```python
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class MetricScore(BaseModel):
    name: str
    score: float
    passed: bool
    details: dict[str, object] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    evaluator_name: str
    score: float
    passed: bool | None = None
    metrics: list[MetricScore] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_passed(self) -> "EvaluationResult":
        if self.passed is None:
            self.passed = all(metric.passed for metric in self.metrics) if self.metrics else self.score >= 1.0
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_understanding_eval.py::test_evaluation_result_computes_pass_flag_from_metric_scores -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/evaluators/__init__.py src/vsa_agent/evaluators/data_models.py tests/unit/evaluators/test_understanding_eval.py
git commit -m "feat: add evaluator shared data models"
```

### Task 2: Add deterministic understanding evaluation

**Files:**
- Create: `src/vsa_agent/evaluators/understanding_eval.py`
- Modify: `tests/unit/evaluators/test_understanding_eval.py`

**Interfaces:**
- Consumes: `UnderstandingResult`, `ExpectedEvent`, `EvaluationResult`
- Produces: `evaluate_understanding_result(actual, expected_summary_terms, expected_events) -> EvaluationResult`

- [ ] **Step 1: Write the failing test**

```python
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.evaluators.data_models import ExpectedEvent
from vsa_agent.evaluators.understanding_eval import evaluate_understanding_result


def test_evaluate_understanding_result_scores_summary_and_event_coverage():
    actual = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person enters loading area and stops near forklift",
        chunks=[],
        events=[],
    )

    result = evaluate_understanding_result(
        actual,
        expected_summary_terms=["person", "forklift"],
        expected_events=[
            ExpectedEvent(label="loading area", description_terms=["stops"]),
        ],
    )

    assert result.evaluator_name == "understanding"
    assert result.score > 0.5
    assert {metric.name for metric in result.metrics} == {"summary_terms", "events"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_understanding_eval.py::test_evaluate_understanding_result_scores_summary_and_event_coverage -v`
Expected: FAIL with import error or missing function

- [ ] **Step 3: Write minimal implementation**

```python
def evaluate_understanding_result(actual, expected_summary_terms, expected_events):
    ...
    return EvaluationResult(
        evaluator_name="understanding",
        score=(summary_score + event_score) / 2.0,
        metrics=[
            MetricScore(name="summary_terms", score=summary_score, passed=summary_score >= 1.0, details={...}),
            MetricScore(name="events", score=event_score, passed=event_score >= 1.0, details={...}),
        ],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_understanding_eval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/evaluators/understanding_eval.py tests/unit/evaluators/test_understanding_eval.py
git commit -m "feat: add deterministic understanding evaluator"
```

### Task 3: Add deterministic search evaluation

**Files:**
- Create: `src/vsa_agent/evaluators/search_eval.py`
- Create: `tests/unit/evaluators/test_search_eval.py`

**Interfaces:**
- Consumes: `SearchOutput`, `ExpectedSearchHit`, `EvaluationResult`
- Produces: `evaluate_search_output(actual, expected_hits) -> EvaluationResult`

- [ ] **Step 1: Write the failing test**

```python
from vsa_agent.evaluators.data_models import ExpectedSearchHit
from vsa_agent.evaluators.search_eval import evaluate_search_output
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult


def test_evaluate_search_output_scores_top_hit_and_hit_coverage():
    actual = SearchOutput(
        data=[
            SearchResult(
                video_name="cam-01.mp4",
                description="person enters loading area",
                start_time="2026-06-19T10:00:00",
                end_time="2026-06-19T10:00:10",
                sensor_id="cam-01",
                screenshot_url="",
                similarity=0.91,
                object_ids=["obj-1"],
            )
        ]
    )

    result = evaluate_search_output(
        actual,
        expected_hits=[
            ExpectedSearchHit(video_name="cam-01.mp4", description_terms=["person", "loading area"], sensor_id="cam-01"),
        ],
    )

    assert result.evaluator_name == "search"
    assert result.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_search_eval.py -v`
Expected: FAIL with import error or missing function

- [ ] **Step 3: Write minimal implementation**

```python
def evaluate_search_output(actual, expected_hits):
    ...
    return EvaluationResult(
        evaluator_name="search",
        score=(top_hit_score + coverage_score) / 2.0,
        metrics=[
            MetricScore(name="top_hit", score=top_hit_score, passed=top_hit_score >= 1.0, details={...}),
            MetricScore(name="hit_coverage", score=coverage_score, passed=coverage_score >= 1.0, details={...}),
        ],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_search_eval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/evaluators/search_eval.py tests/unit/evaluators/test_search_eval.py
git commit -m "feat: add deterministic search evaluator"
```

### Task 4: Add deterministic report evaluation

**Files:**
- Create: `src/vsa_agent/evaluators/report_eval.py`
- Create: `tests/unit/evaluators/test_report_eval.py`

**Interfaces:**
- Consumes: `str`, `ExpectedReportSection`, `EvaluationResult`
- Produces: `evaluate_report_markdown(markdown, expected_sections, required_terms=None) -> EvaluationResult`

- [ ] **Step 1: Write the failing test**

```python
from vsa_agent.evaluators.data_models import ExpectedReportSection
from vsa_agent.evaluators.report_eval import evaluate_report_markdown


def test_evaluate_report_markdown_scores_required_sections_and_terms():
    markdown = "# Report\n\n## Summary\nperson near forklift\n\n## Timeline\n- event"

    result = evaluate_report_markdown(
        markdown,
        expected_sections=[
            ExpectedReportSection(title="Summary", required_terms=["person"]),
            ExpectedReportSection(title="Timeline", required_terms=["event"]),
        ],
        required_terms=["forklift"],
    )

    assert result.evaluator_name == "report"
    assert result.score == 1.0
    assert result.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_report_eval.py -v`
Expected: FAIL with import error or missing function

- [ ] **Step 3: Write minimal implementation**

```python
def evaluate_report_markdown(markdown, expected_sections, required_terms=None):
    ...
    return EvaluationResult(
        evaluator_name="report",
        score=(section_score + term_score) / 2.0,
        metrics=[
            MetricScore(name="sections", score=section_score, passed=section_score >= 1.0, details={...}),
            MetricScore(name="required_terms", score=term_score, passed=term_score >= 1.0, details={...}),
        ],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_report_eval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/evaluators/report_eval.py tests/unit/evaluators/test_report_eval.py
git commit -m "feat: add deterministic report evaluator"
```

### Task 5: Regression run and plan sync

**Files:**
- Modify: `docs/superpowers/vsa-agent-implementation-plan.md`

**Interfaces:**
- Consumes: evaluator modules from Tasks 1-4
- Produces: updated gap status in the master implementation plan

- [ ] **Step 1: Run evaluator regression**

Run: `conda run -n vsa-agent python -m pytest tests/unit/evaluators/test_understanding_eval.py tests/unit/evaluators/test_search_eval.py tests/unit/evaluators/test_report_eval.py -q`
Expected: `PASS`

- [ ] **Step 2: Update the master implementation plan status**

```markdown
### 当前验证状态（2026-06-23）
- [x] 已创建专用 `conda` 环境 `vsa-agent`
- [x] 已完成环境安装：`python -m pip install -e ".[dev]" elasticsearch`
- [x] 已修复 FastAPI 路由枚举兼容问题
- [x] 已修复代理环境变量导致的 `httpx` / `ChatOpenAI` 初始化失败
- [x] 已完成全量回归验证：`406 passed, 2 warnings`
- [x] 已补齐 `evaluators/` 最小确定性评估框架

### 未实现模块 (Gap)

无
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/vsa-agent-implementation-plan.md
git commit -m "docs: close evaluators gap in implementation plan"
```

## Self-Review

- Spec coverage: this plan covers the only remaining `evaluators/` gap and limits scope to deterministic understanding/search/report checks.
- Placeholder scan: no `TBD`, `TODO`, or cross-task shorthand remains.
- Type consistency: all tasks reuse `EvaluationResult` and expected fixture models defined in Task 1.
