# vsa-agent Implementation Plan — Part 2: Tools & Agents

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现工业安全视频分析的核心工具和Agent工作流（视频帧提取、VLM理解、搜索Agent、摘要Agent、Critic自检环、后处理管线）。

**Architecture:** TDD驱动，每个模块先从测试开始。工具用@register_tool注册，Agent用LangGraph StateGraph构建DAG。

**Tech Stack:** Python 3.13, LangChain, LangGraph, langchain-openai, OpenCV, FFmpeg, Pydantic

---

## Task 8: 视频帧提取工具 (Design Pattern #1 #10)

**Files:**
- Create: tests/unit/test_frame_extract.py
- Create: src/vsa_agent/tools/frame_extract.py

**Learning:** OpenCV视频处理、帧采样策略

- [ ] **Step 1: Write failing test**

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

- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

## Task 9: VLM视频理解工具 (Design Pattern #2 #11)

**Files:**
- Create: tests/unit/test_video_understanding.py
- Create: src/vsa_agent/tools/video_understanding.py

**Learning:** VLM多模态调用、意图感知prompt模板

- [ ] **Step 1: Write test with mock VLM adapter**
- [ ] **Step 2: Implement frame → VLM → caption pipeline**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

## Task 10: Search Agent (Design Pattern #13 #9)

**Files:**
- Create: tests/unit/agents/test_search_agent.py
- Create: src/vsa_agent/agents/search_agent.py
- Create: src/vsa_agent/tools/query_builders.py

**Learning:** 三路搜索策略、ES查询构建器

- [ ] **Step 1: Write test with mock tools**
- [ ] **Step 2: Implement three-path routing (embed/attribute/fusion)**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

## Task 11: Summary Agent (Design Pattern #11 #20)

**Files:**
- Create: tests/unit/agents/test_summary_agent.py
- Create: src/vsa_agent/agents/summary_agent.py

**Learning:** 长视频分片策略、VLM聚合、安全报告生成

- [ ] **Step 1: Write test with mock VLM**
- [ ] **Step 2: Implement chunk → caption → aggregate → report pipeline**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

## Task 12: Critic Agent (Design Pattern #7)

**Files:**
- Create: tests/unit/agents/test_critic_agent.py
- Create: src/vsa_agent/agents/critic_agent.py

**Learning:** 自检环、LLM评估

- [ ] **Step 1: Write test — Critic must reject incomplete reports**
- [ ] **Step 2: Implement safety checklist validator**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

## Task 13: Postprocessing管线 (Design Pattern #4 #10)

**Files:**
- Create: tests/unit/agents/postprocess/test_pipeline.py
- Create: src/vsa_agent/agents/postprocess/pipeline.py
- Create: src/vsa_agent/agents/postprocess/validators/{base,non_empty,url_check,safety_checklist}.py

**Learning:** 责任链模式、验证器注册表

- [ ] **Step 1: Write test for each validator**
- [ ] **Step 2: Implement ValidationPipeline + validators**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

---

> Next: Part 3 covers evaluators, integrations, and server deployment.
