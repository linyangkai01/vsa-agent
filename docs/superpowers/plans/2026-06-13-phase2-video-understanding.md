# Phase 2 视频理解实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 完成 Phase 2 的视频理解链路，实现统一结构化结果和文本结果双轨输出。

**架构：** 先复用已经落地的共享理解模型和 `prompt_gen`，然后把 `video_understanding` 收敛到统一契约，再增加 `lvs_video_understanding` 和 `vss_summarize`，最后补业务流验收测试。短视频和长视频都先输出 `UnderstandingResult`，最终再由 `vss_summarize` 生成 `SummaryResult`。

**技术栈：** Python 3.12、Pydantic v2、LangChain messages、OpenAI-compatible model adapter、pytest、pytest-asyncio、OpenCV

---

## 当前基线

已存在并可复用：
- `src/vsa_agent/data_models/understanding.py`
- `tests/unit/data_models/test_understanding_models.py`
- `src/vsa_agent/tools/prompt_gen.py`
- `tests/unit/tools/test_prompt_gen.py`

因此本计划从 `video_understanding` 的契约收敛开始，不重复实现已存在的模型和 prompt 工具。

## 文件结构

**新增文件**
- `src/vsa_agent/tools/lvs_video_understanding.py`
  长视频切块、逐块调用、结果归并
- `src/vsa_agent/tools/vss_summarize.py`
  从结构化理解结果生成文本总结和双轨输出
- `tests/unit/tools/test_lvs_video_understanding.py`
  长视频编排测试
- `tests/unit/tools/test_vss_summarize.py`
  总结层测试

**修改文件**
- `src/vsa_agent/tools/video_understanding.py`
  收敛到统一输出 `UnderstandingResult`，补 `ISO/offset`、URL translation、retry
- `src/vsa_agent/tools/register.py`
  注册 `lvs_video_understanding`、`vss_summarize`
- `src/vsa_agent/config.py`
  视需要补长视频配置
- `config_test.yaml`
  视需要补长视频默认测试配置
- `tests/unit/tools/test_video_understanding.py`
  从字符串输出测试升级为结构化结果测试
- `tests/acceptance/test_video_understanding_flow.py`
  改为验证双轨输出主链

---

### Task 1：收敛 `video_understanding.py` 契约

**Files:**
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [x] **Step 1: 写失败测试，要求 `analyze_video_segment()` 返回 `UnderstandingResult`**

```python
import pytest

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.video_understanding import analyze_video_segment


@pytest.mark.anyio
async def test_analyze_video_segment_with_frames_returns_understanding_result():
    class FakeResponse:
        content = "person walking near forklift"

    class FakeAdapter:
        async def invoke(self, messages):
            return FakeResponse()

    result = await analyze_video_segment(
        frames=["frame-a"],
        query="what happened",
        model_adapter=FakeAdapter(),
    )

    assert isinstance(result, UnderstandingResult)
    assert result.summary_text == "person walking near forklift"
    assert result.source_type == "video_file"
```

- [x] **Step 2: 写失败测试，验证 `offset` 时间格式归一化**

```python
from vsa_agent.tools.video_understanding import _normalize_model_response


def test_normalize_model_response_uses_offset_time_format():
    result = _normalize_model_response(
        query="what happened",
        source_type="video_file",
        raw_output="person walking",
        prompt_used="watch carefully",
        start_timestamp=5,
        end_timestamp=9,
        thinking=None,
        time_format="offset",
        video_path="a.mp4",
    )
    assert result.chunks[0].start_timestamp == "PT5S"
    assert result.chunks[0].end_timestamp == "PT9S"
```

- [x] **Step 3: 写失败测试，验证 translated source 会先做 URL 翻译**

```python
import pytest

from vsa_agent.config import VideoUnderstandingConfig
from vsa_agent.tools.video_understanding import _prepare_video_path


def test_prepare_video_path_translates_remote_source(monkeypatch):
    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding.translate_url",
        lambda url: "C:/tmp/video.mp4",
    )
    config = VideoUnderstandingConfig(source_mode="translated")
    assert _prepare_video_path("https://example.com/video.mp4", config) == "C:/tmp/video.mp4"
```

- [x] **Step 4: 写失败测试，验证模型调用会重试**

```python
import pytest

from vsa_agent.config import VideoUnderstandingConfig
from vsa_agent.tools.video_understanding import _analyze_frames


@pytest.mark.anyio
async def test_analyze_frames_retries_on_transient_failure():
    class FakeAdapter:
        def __init__(self):
            self.calls = 0

        async def invoke(self, messages):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("temporary error")
            return type("Resp", (), {"content": "recovered output"})()

    adapter = FakeAdapter()
    result = await _analyze_frames(
        ["frame-a"],
        "what happened",
        model_adapter=adapter,
        config=VideoUnderstandingConfig(max_retries=3),
    )
    assert result == "recovered output"
    assert adapter.calls == 3
```

- [x] **Step 5: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: 至少 1 个失败，说明契约测试真正覆盖了当前行为

- [x] **Step 6: 只做最小实现修正**

目标：
- `analyze_video_segment()` 始终返回 `UnderstandingResult`
- `_normalize_model_response()` 正确输出 `iso/offset`
- `_prepare_video_path()` 对 translated source 做本地化检查
- `_analyze_frames()` 保持有限重试

- [x] **Step 7: 回跑 `video_understanding` 单测**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: stabilize phase2 video understanding contract"
```

### Task 2：实现 `lvs_video_understanding.py`

**Files:**
- Create: `src/vsa_agent/tools/lvs_video_understanding.py`
- Modify: `src/vsa_agent/tools/register.py`
- Test: `tests/unit/tools/test_lvs_video_understanding.py`

- [x] **Step 1: 写失败测试，定义长视频切块函数**

```python
from vsa_agent.tools.lvs_video_understanding import split_video_into_chunks


def test_split_video_into_chunks():
    chunks = split_video_into_chunks(duration_sec=95, chunk_duration_sec=30)
    assert chunks == [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0), (90.0, 95.0)]
```

- [x] **Step 2: 写失败测试，定义 chunk 结果归并**

```python
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.lvs_video_understanding import merge_chunk_results


def test_merge_chunk_results_combines_summary_text():
    a = UnderstandingResult(query="q", source_type="video_file", summary_text="chunk a")
    b = UnderstandingResult(query="q", source_type="video_file", summary_text="chunk b")
    merged = merge_chunk_results("q", "video_file", [a, b])
    assert "chunk a" in merged.summary_text
    assert "chunk b" in merged.summary_text
```

- [x] **Step 3: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_lvs_video_understanding.py -v`
Expected: FAIL with import error

- [x] **Step 4: 实现最小切块与归并**

最小实现应包含：
- `split_video_into_chunks()`
- `merge_chunk_results()`
- `analyze_long_video()`：逐 chunk 调用 `analyze_video_segment()`

- [x] **Step 5: 注册工具并跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_lvs_video_understanding.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/vsa_agent/tools/lvs_video_understanding.py src/vsa_agent/tools/register.py tests/unit/tools/test_lvs_video_understanding.py
git commit -m "feat: add long video understanding orchestrator"
```

### Task 3：实现 `vss_summarize.py`

**Files:**
- Create: `src/vsa_agent/tools/vss_summarize.py`
- Modify: `src/vsa_agent/tools/register.py`
- Test: `tests/unit/tools/test_vss_summarize.py`

- [x] **Step 1: 写失败测试，定义双轨输出**

```python
import pytest

from vsa_agent.data_models.understanding import SummaryResult
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.vss_summarize import summarize_understanding_result


@pytest.mark.anyio
async def test_summarize_understanding_result_returns_summary_result():
    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person walking",
        chunks=[],
        events=[],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert isinstance(summary, SummaryResult)
    assert summary.structured_output.query == "what happened"
    assert summary.text_output == "person walking"
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_vss_summarize.py -v`
Expected: FAIL with import error

- [x] **Step 3: 写最小实现**

最小实现应满足：
- 接收 `UnderstandingResult`
- 生成 `SummaryResult`
- 文本优先复用 `summary_text`
- 保留完整 `structured_output`

- [x] **Step 4: 注册工具并跑测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_vss_summarize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vsa_agent/tools/vss_summarize.py src/vsa_agent/tools/register.py tests/unit/tools/test_vss_summarize.py
git commit -m "feat: add phase2 summary layer"
```

### Task 4：补 Phase 2 验收流

**Files:**
- Modify: `tests/acceptance/test_video_understanding_flow.py`

- [x] **Step 1: 写短视频双轨输出验收测试**

```python
import pytest

from vsa_agent.data_models.understanding import SummaryResult
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.vss_summarize import summarize_understanding_result


@pytest.mark.anyio
async def test_short_video_returns_dual_track_output():
    result = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="person walking near forklift",
        chunks=[],
        events=[],
    )
    summary = await summarize_understanding_result(result, "what happened")
    assert isinstance(summary, SummaryResult)
    assert summary.text_output
    assert summary.structured_output
```

- [x] **Step 2: 写长视频链路验收测试**

```python
import pytest

from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools.lvs_video_understanding import merge_chunk_results


def test_long_video_pipeline_returns_merged_understanding_result():
    chunk_a = UnderstandingResult(query="what happened", source_type="video_file", summary_text="chunk a")
    chunk_b = UnderstandingResult(query="what happened", source_type="video_file", summary_text="chunk b")
    merged = merge_chunk_results("what happened", "video_file", [chunk_a, chunk_b])
    assert "chunk a" in merged.summary_text
    assert "chunk b" in merged.summary_text
```

- [x] **Step 3: 运行验收测试**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_video_understanding_flow.py -v`
Expected: PASS

- [x] **Step 4: 跑全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_video_understanding_flow.py
git commit -m "test: add phase2 acceptance coverage"
```

---

## 自检

### 覆盖性检查
- 共享理解模型：已存在，不在本轮重复实现
- `prompt_gen.py`：已存在，不在本轮重复实现
- `video_understanding.py` 的结构化输出、时间格式、retry、translated source：由 Task 1 覆盖
- `lvs_video_understanding.py` 的切块与编排：由 Task 2 覆盖
- `vss_summarize.py` 的双轨输出：由 Task 3 覆盖
- 短视频 / 长视频 / 双轨输出业务流：由 Task 4 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都给了明确文件路径、测试命令和最小实现范围

### 命名一致性检查
- 统一使用 `UnderstandingResult` 作为中间结果
- 统一使用 `SummaryResult` 作为最终输出
- 统一使用 `analyze_video_segment` / `analyze_long_video` / `summarize_understanding_result`

### 执行说明
- 当前分支已经存在部分 Phase 2 前置工作，实现时应先复用已有代码，再补缺口
- 严格按 TDD：先写失败测试，再修实现，再回归
