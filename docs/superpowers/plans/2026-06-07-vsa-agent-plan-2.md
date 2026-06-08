# vsa-agent Implementation Plan — Part 2: Tools & Agents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现工业安全视频分析的核心工具和Agent工作流（视频帧提取、VLM理解、搜索Agent、摘要Agent、Critic自检环、后处理管线）。

**Architecture:** TDD驱动，每个模块先从测试开始。工具用@register_tool注册，Agent用LangGraph StateGraph构建DAG。

**Tech Stack:** Python 3.13, LangChain, LangGraph, langchain-openai, OpenCV, FFmpeg, Pydantic

---

## Task 8: ✅ **DONE** 视频帧提取工具 (Design Pattern #1 #10)

**Files:**
- Create: tests/unit/test_frame_extract.py
- Create: src/vsa_agent/tools/frame_extract.py

**Learning:** OpenCV视频处理、帧采样策略

- [x] **Step 1: Write failing test**

`python
# tests/unit/test_frame_extract.py
import os, tempfile
import numpy as np
import cv2
import pytest
import asyncio
from vsa_agent.registry import ToolRegistry

def _create_test_video(path: str, duration_sec=3, fps=10):
    '''Create a simple test MP4 with colored frames.'''
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, fps, (320, 240))
    for i in range(duration_sec * fps):
        frame = np.full((240, 320, 3), (i * 10, 100, 200), dtype=np.uint8)
        out.write(frame)
    out.release()

class TestFrameExtract:
    def test_extract_frames_basic(self):
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            _create_test_video(f.name, duration_sec=3, fps=10)
            video_path = f.name

        fn = ToolRegistry.get('frame_extract')
        result = asyncio.run(fn(video_path=video_path, max_frames=5))
        assert len(result['frames']) == 5
        assert result['duration_sec'] == 3
        os.unlink(video_path)
`

- [x] **Step 2: Write implementation**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

## Task 9: ✅ **DONE** VLM视频理解工具 (Design Pattern #2 #11)

**Files:**
- Create: tests/unit/test_video_understanding.py
- Create: src/vsa_agent/tools/video_understanding.py

**Learning:** VLM多模态调用、意图感知prompt模板

- [x] **Step 1: Write test with mock VLM adapter**
- [x] **Step 2: Implement frame → VLM → caption pipeline**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

## Task 10: ✅ **DONE** Search Agent (Design Pattern #13 #9)

**Files:**
- Create: tests/unit/agents/test_search_agent.py
- Create: src/vsa_agent/agents/search_agent.py
- Create: src/vsa_agent/tools/query_builders.py

**Learning:** 三路搜索策略、ES查询构建器

- [x] **Step 1: Write test with mock tools**
- [x] **Step 2: Implement three-path routing (embed/attribute/fusion)**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

## Task 11: Summary Agent (Design Pattern #11 #20)

**Files:**
- Create: tests/unit/agents/test_summary_agent.py
- Create: src/vsa_agent/agents/summary_agent.py

**Learning:** 长视频分片策略、VLM聚合、安全报告生成

- [x] **Step 1: Write test with mock VLM**
- [x] **Step 2: Implement chunk → caption → aggregate → report pipeline**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

## Task 12: Critic Agent (Design Pattern #7)

**Files:**
- Create: tests/unit/agents/test_critic_agent.py
- Create: src/vsa_agent/agents/critic_agent.py

**Learning:** 自检环、LLM评估

- [x] **Step 1: Write test — Critic must reject incomplete reports**
- [x] **Step 2: Implement safety checklist validator**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

## Task 13: Postprocessing管线 (Design Pattern #4 #10)

**Files:**
- Create: tests/unit/agents/postprocess/test_pipeline.py
- Create: src/vsa_agent/agents/postprocess/pipeline.py
- Create: src/vsa_agent/agents/postprocess/validators/{base,non_empty,url_check,safety_checklist}.py

**Learning:** 责任链模式、验证器注册表

- [x] **Step 1: Write test for each validator**
- [x] **Step 2: Implement ValidationPipeline + validators**
- [x] **Step 3: Run tests → pass**
- [x] **Step 4: Commit**

---

> Next: Part 3 covers evaluators, integrations, and server deployment.


---

# Part 3: 进阶功能完善 (Advanced Features)

> 简化审计：当前完成的核心功能大部分是对 NVIDIA 原版的简化实现。本部分列出所有简化项。
> 标注: 🔷 = 简化 (Simplified), ✅ = 与原版一致 (Matches Original)

## 各模块简化审计

### Task 0-6

| 文件 | 审计 |
|------|------|
| config.py | 🔷 PromptsConfig空桩化，SearchConfig 20+字段省略 |
| registry.py | 🔷 原版NAT框架，vsa-agent用简单ToolRegistry |
| model_adapter/ | 🔷 原版多模型+retry+streaming，vsa仅OpenAI+vLLM |
| top_agent.py | 🔷 原版planning/reasoning，vsa简化版 |
| data_models.py | ✅ 结构对应 |
| api/routes.py | 🔷 原版streaming/video_upload/RTSP，vsa仅POST/chat |
| mcp/server.py | ✅ 对应原版 |

### Task 8: frame_extract.py

| 功能 | 审计 |
|------|------|
| frame_select() | ✅ 对应原版 |
| has_nvidia_gpu() | 🔷 省略 |
| 单次VideoCapture | 🔷 简化(review后修复) |
| 批量帧处理 | 🔷 省略(partition分批调VLM) |

### Task 9: video_understanding.py

| 功能 | 审计 |
|------|------|
| VLM调用 | ✅ 一致 |
| VSS backend | 🔷 省略 |
| retry logic | 🔷 省略 |
| thinking tag解析 | 🔷 省略 |
| Cosmos model | 🔷 省略 |
| max_frames保护 | ✅ 已添加 |

### Task 10: search_agent.py + search tools

| 功能 | 审计 |
|------|------|
| DecomposedQuery | ✅ 一致 |
| SearchResult/SearchOutput | ✅ 一致 |
| decompose_query() | 🔷 简化 |
| 三路由(Path1/2/3) | ✅ 一致 |
| fusion_search_rerank() | 🔷 省略(RRF+weighted_linear) |
| embed_confidence_threshold | 🔷 省略 |
| critic agent循环 | 🔷 省略 |
| SearchConfig(20+fields) | 🔷 省略 |
| execute_core_search async gen | 🔷 省略 |
| InMemoryVectorStore | 🔷 placeholder(生产需替换ES) |

---

## 进阶功能清单

### P0: 必须完善
- [ ] fusion_search_rerank() -- RRF + weighted_linear融合算法
- [ ] SearchConfig完整字段 -- w_embed,w_attribute,rrf_k,rrf_w
- [ ] execute_core_search async generator -- 流式输出AgentMessageChunk
- [ ] Elasticsearch backend -- 替换InMemoryVectorStore
- [ ] ES Query Builders -- Incident/Frames/Behavior QueryBuilder

### P1: 重要完善
- [ ] critic agent -- VLM校验+重新搜索循环
- [ ] VLM retry logic -- max_retries+提示改写
- [ ] thinking tag解析 -- parse_content_blocks()
- [ ] Cosmos model支持 -- mm_processor_kwargs/media_io_kwargs
- [ ] VSS backend -- 视频上传+摘要通过VSS
- [ ] attribute_result_to_search_result()转换函数
- [ ] has_nvidia_gpu() -- GPU检测
- [ ] top_agent流式输出 -- 完整streaming
- [ ] API完善 -- video_upload, RTSP endpoints

### P2: 可选完善
- [ ] evaluators -- customized_qa, trajectory, report
- [ ] video_analytics -- ES client, embeddings
- [ ] embed/模块 -- CosmosEmbedClient, RTVI CV Embed
- [ ] utils/工具 -- async_mixin, url_translation, retry
- [ ] vst/工具 -- duration, sensor_list, snapshot, timeline

---

> 更新日期: 2026-06-08
> 当前进度: Task 8/9/10 完成, 待开始 Task 11
