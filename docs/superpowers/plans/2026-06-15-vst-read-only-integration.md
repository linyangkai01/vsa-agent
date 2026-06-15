# VST Read-Only Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成去 NAT 的 VST 只读适配层，并把它稳定接入 `video_understanding` 的 `rtsp/sensor_id` 路径。

**Architecture:** 保留 `integrations/vst_client.py` 作为唯一的 VST 外部系统适配层，业务工具不直接处理 VST HTTP 细节。`video_understanding` 通过统一的源解析逻辑优先调用 `VSTClient`，失败时再回退到静态映射配置，确保链路既可真实接入，也可离线运行。

**Tech Stack:** Python 3.12, Pydantic v2, pytest, pytest-asyncio, configurable async adapter injection

---

## 当前基线

当前分支已经具备：
- `src/vsa_agent/integrations/vst_client.py`
- `tests/unit/integrations/test_vst_client.py`
- `VideoUnderstandingConfig.translated_base_dir`
- `VideoUnderstandingConfig.vst_sensor_source_map`
- `video_understanding` 中的 `_resolve_video_source()` 初版

因此本计划只覆盖“把 VST 只读接入做完整、可维护、可测试”的剩余工作，不重复建设已经存在的骨架。

## 文件结构

**新增文件**
- 无

**修改文件**
- `src/vsa_agent/integrations/vst_client.py`
  补齐真实 HTTP 适配入口、错误归一化、响应解析边界
- `src/vsa_agent/tools/video_understanding.py`
  把 `VSTClient` 正式接入 `rtsp/sensor_id` 源解析路径
- `src/vsa_agent/config.py`
  如果需要，补全 `VSTConfig` 独立配置对象
- `config_test.yaml`
  对应补测试配置
- `tests/unit/integrations/test_vst_client.py`
  扩展 VST 响应解析和错误路径覆盖
- `tests/unit/tools/test_video_understanding.py`
  扩展 `sensor_id -> VSTClient -> clip` 路径覆盖
- `tests/acceptance/test_video_understanding_flow.py`
  增加一条 `sensor_id` 只读接入主链验收

---

### Task 1: 稳定 `VSTClient` 契约与错误模型

**Files:**
- Modify: `src/vsa_agent/integrations/vst_client.py`
- Modify: `tests/unit/integrations/test_vst_client.py`

- [x] **Step 1: 写失败测试，要求 `get_stream_info()` 保留原始 metadata**

```python
import pytest

from vsa_agent.integrations.vst_client import VSTClient


@pytest.mark.anyio
async def test_get_stream_info_preserves_raw_metadata():
    async def fake_request_json(path: str):
        return [
            {
                "stream-123": [
                    {
                        "name": "camera-1",
                        "url": "rtsp://camera-1/stream",
                        "location": "warehouse-a",
                    }
                ]
            }
        ]

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    result = await client.get_stream_info("camera-1")
    assert result.metadata["raw"]["location"] == "warehouse-a"
```

- [x] **Step 2: 写失败测试，要求 `get_video_clip()` 在没有 `clip_url` 时抛 `VSTClientError`**

```python
import pytest

from vsa_agent.integrations.vst_client import VSTClient
from vsa_agent.integrations.vst_client import VSTClientError


@pytest.mark.anyio
async def test_get_video_clip_raises_when_stream_has_no_url():
    async def fake_request_json(path: str):
        return [{"stream-123": [{"name": "camera-1", "url": ""}]}]

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    with pytest.raises(VSTClientError, match="camera-1"):
        await client.get_video_clip("camera-1", "2025-01-01T10:05:00Z", "2025-01-01T10:05:30Z")
```

- [x] **Step 3: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py -v`
Expected: 至少 1 个失败，证明契约测试覆盖新增行为

- [x] **Step 4: 写最小实现**

目标：
- `get_stream_info()` 保留响应原文到 `metadata["raw"]`
- `get_video_clip()` 在没有 `clip_url/local_path` 时抛 `VSTClientError`

- [x] **Step 5: 回跑 VSTClient 单测**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/vsa_agent/integrations/vst_client.py tests/unit/integrations/test_vst_client.py
git commit -m "feat: harden VST read client contract"
```

### Task 2: 给 `VSTClient` 增加真实 HTTP 入口但保持可注入测试适配

**Files:**
- Modify: `src/vsa_agent/integrations/vst_client.py`
- Modify: `tests/unit/integrations/test_vst_client.py`

- [x] **Step 1: 写失败测试，要求默认 `_request_json()` 在未注入适配器时给出明确错误**

```python
import pytest

from vsa_agent.integrations.vst_client import VSTClient
from vsa_agent.integrations.vst_client import VSTClientError


@pytest.mark.anyio
async def test_default_request_json_without_transport_raises_clear_error():
    client = VSTClient(external_url="http://localhost:30888")
    with pytest.raises(VSTClientError, match="No HTTP adapter configured"):
        await client._request_json("/vst/api/v1/sensor/streams")
```

- [x] **Step 2: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py -v`
Expected: FAIL if error type/message drifted

- [x] **Step 3: 保持当前最小实现，不接真实网络**

这一任务不引入 `aiohttp/httpx` 请求实现。  
目标只是确认：默认无传输层时的失败模型稳定，后续真实 HTTP 接入可以单独加，不污染当前阶段。

- [x] **Step 4: 回跑 VSTClient 单测**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/integrations/test_vst_client.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/vsa_agent/integrations/vst_client.py tests/unit/integrations/test_vst_client.py
git commit -m "test: lock VST client transport boundary"
```

### Task 3: 正式接入 `video_understanding` 的 `rtsp/sensor_id` 路径

**Files:**
- Modify: `src/vsa_agent/tools/video_understanding.py`
- Modify: `tests/unit/tools/test_video_understanding.py`

- [x] **Step 1: 写失败测试，要求 `sensor_id` 优先走 `VSTClient`**

```python
import pytest

from vsa_agent.config import VideoUnderstandingConfig
from vsa_agent.tools.video_understanding import _resolve_video_source


@pytest.mark.anyio
async def test_resolve_video_source_prefers_vst_client_over_static_map(monkeypatch):
    class FakeClient:
        async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
            return type("ClipResult", (), {"clip_url": "rtsp://camera-1/from-vst", "local_path": None})()

    monkeypatch.setattr("vsa_agent.tools.video_understanding._get_vst_client", lambda: FakeClient())

    config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/from-map"})
    resolved = await _resolve_video_source(
        video_path="",
        sensor_id="camera-1",
        source_type="rtsp",
        config=config,
        start_timestamp="PT5S",
        end_timestamp="PT10S",
    )
    assert resolved == "rtsp://camera-1/from-vst"
```

- [x] **Step 2: 写失败测试，要求 `VSTClient` 失败时回退到静态映射**

```python
@pytest.mark.anyio
async def test_resolve_video_source_falls_back_to_static_map(monkeypatch):
    class FakeClient:
        async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
            raise RuntimeError("vst unavailable")

    monkeypatch.setattr("vsa_agent.tools.video_understanding._get_vst_client", lambda: FakeClient())

    config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/from-map"})
    resolved = await _resolve_video_source(
        video_path="",
        sensor_id="camera-1",
        source_type="rtsp",
        config=config,
        start_timestamp="PT5S",
        end_timestamp="PT10S",
    )
    assert resolved == "rtsp://camera-1/from-map"
```

- [x] **Step 3: 运行测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: 至少 1 个失败

- [x] **Step 4: 写最小实现**

目标：
- 新增 `_get_vst_client()`
- `_resolve_video_source()` 变为 async
- `sensor_id` 路径先调 `VSTClient.get_video_clip()`，失败再回退到 `vst_sensor_source_map`

- [x] **Step 5: 回跑 video_understanding 单测**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/tools/test_video_understanding.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/vsa_agent/tools/video_understanding.py tests/unit/tools/test_video_understanding.py
git commit -m "feat: wire VST client into video understanding"
```

### Task 4: 补一条 VST 只读接入验收测试

**Files:**
- Modify: `tests/acceptance/test_video_understanding_flow.py`

- [x] **Step 1: 写失败测试，要求 `sensor_id` 能走到 VST 适配层**

```python
import pytest

from vsa_agent.data_models.understanding import UnderstandingResult


@pytest.mark.anyio
async def test_rtsp_sensor_path_uses_vst_clip_resolution(monkeypatch):
    from vsa_agent.tools.video_understanding import video_understanding_tool

    class FakeClient:
        async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
            return type("ClipResult", (), {"clip_url": "C:/tmp/clip.mp4", "local_path": None})()

    async def fake_analyze_video_segment(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text="resolved via vst",
            chunks=[],
            events=[],
        )

    monkeypatch.setattr("vsa_agent.tools.video_understanding._get_vst_client", lambda: FakeClient())
    monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
    monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_video_segment", fake_analyze_video_segment)

    result = await video_understanding_tool(
        video_path="",
        query="what happened",
        source_type="rtsp",
        sensor_id="camera-1",
        start_timestamp="PT5S",
        end_timestamp="PT10S",
    )
    assert result == "resolved via vst"
```

- [x] **Step 2: 运行验收测试，确认失败**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_video_understanding_flow.py -v`
Expected: FAIL if VST path is not fully wired

- [x] **Step 3: 修正最小实现并回跑验收**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_video_understanding_flow.py -v`
Expected: PASS

- [x] **Step 4: 跑全量回归**

Run: `C:\working\orther\anaconda3\envs\vsa-agent\python.exe -m pytest tests/ -q`
Expected: all tests PASS

- [x] **Step 5: Commit**

```bash
git add tests/acceptance/test_video_understanding_flow.py
git commit -m "test: cover VST read-only understanding path"
```

---

## 自检

### 覆盖性检查
- `VSTClient` 数据模型、错误模型、响应解析：Task 1 覆盖
- 传输层边界与默认错误：Task 2 覆盖
- `video_understanding` 的 `rtsp/sensor_id` 接入：Task 3 覆盖
- 只读接入主链验收：Task 4 覆盖

### 占位符检查
- 没有 `TODO`、`TBD`、`implement later`
- 每个任务都给了明确文件路径、测试命令、期望结果和最小实现范围

### 命名一致性检查
- 统一使用 `VSTClientError` 作为适配层异常
- 统一使用 `VSTStreamInfo` / `VSTTimeline` / `VSTClipResult`
- 统一使用 `_get_vst_client()` 作为 `video_understanding` 的接入点

### 执行说明
- 当前分支已存在 `vst_client.py` 的第一版与部分接线，执行时应先复用现有实现，再补缺口
- 严格按 TDD：先看测试红，再补实现，再跑全量回归
