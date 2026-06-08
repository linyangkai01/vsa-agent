# vsa-agent Implementation Plan — Part 2: Completion Sprint

> 基于三个审计文档 (2026-06-08) 重新编排的任务序列。
> 全项目基线: 34/93 = 37%
> 每个 task 完成后更新完成率。

---

## 已完成的 Task (8-10)

| Task | 模块 | 完成率 | 审计文档 |
|------|------|--------|----------|
| 8 | frame_extract.py | 1/2 = 50% | task6-10-audit.md |
| 9 | video_understanding.py | 1/7 = 14% | task6-10-audit.md |
| 10a | search_agent.py + search.py | 9/24 = 38% | search-module-audit.md |
| 10b | embed/attribute search tools | 3/25 = 12% | search-module-audit.md |

---

## Phase A: 补齐已有模块的缺失函数 (P0)

目标: 三大模块完成率从 12-38% 提升到 60%+

### Task 14: 补齐 tools/search.py — 搜索核心函数

**审计:** 当前 6/15 = 40%，缺失 9 项
**目标:** 10/15 = 67%

- [ ] **14.1** `class SearchConfig` — 20+ 配置字段 (w_embed, w_attribute, rrf_k, rrf_w, fusion_method, embed_confidence_threshold)
- [ ] **14.2** `class SearchInput` — 输入模型 (query, source_type, video_sources, timestamp, top_k, agent_mode, use_critic)
- [ ] **14.3** `execute_core_search()` — async generator，替代 agents/search_agent.py 的 execute_search()
- [ ] **14.4** `_run_attribute_only_search()` — 独立化属性搜索封装 (当前逻辑在 agents/ 中)

### Task 15: 补齐 tools/embed_search.py — 语义搜索

**审计:** 当前 1/9 = 11%，缺失 8 项
**目标:** 5/9 = 56%

- [ ] **15.1** `class EmbedSearchResultItem` — 7 字段 Pydantic 模型
- [ ] **15.2** `class EmbedSearchOutput` — query_embedding + results
- [ ] **15.3** `class QueryInput` — params/prompts/embeddings/source_type/exclude_videos
- [ ] **15.4** `_generate_query_embedding()` — 文本→向量 (先 mock,后续接 ES)
- [ ] **15.5** `_process_search_hit()` — ES hit → EmbedSearchResultItem (先 mock)

### Task 16: 补齐 tools/attribute_search.py — 属性搜索

**审计:** 当前 2/16 = 13%，缺失 14 项
**目标:** 6/16 = 38% (核心缺失太多,分两批)

- [ ] **16.1** `class AttributeSearchInput` — 8 字段 Pydantic 模型
- [ ] **16.2** `class AttributeSearchMetadata` — 8 字段 (sensor_id, object_id, bbox, scores 等)
- [ ] **16.3** `class AttributeSearchResult` — screenshot_url + metadata
- [ ] **16.4** `search_by_attributes()` — 属性搜索核心函数 (先 mock)

---

## Phase B: 补齐已有模块的缺失函数 (P1)

### Task 17: 补齐 agents/search_agent.py

**审计:** 当前 3/9 = 33%
**目标:** 6/9 = 67%

- [ ] **17.1** `class SearchAgentConfig` — 20+ 字段 (embed_search_tool, attribute_search_tool, agent_mode_llm 等)
- [ ] **17.2** `_to_incidents_output()` — SearchOutput → JSON (presentation converter)
- [ ] **17.3** `_to_search_results()` — 原始结果 → SearchResult 列表 (presentation converter)

### Task 18: 补齐 tools/video_understanding.py

**审计:** 当前 1/11 = 9% (含 video_caption 合并)
**目标:** 4/11 = 36%

- [ ] **18.1** `class VideoUnderstandingInput` — Pydantic 输入模型 (sensor_id, start/end_timestamp, user_prompt)
- [ ] **18.2** VLM retry logic — max_retries + 提示改写
- [ ] **18.3** `_parse_thinking_from_content()` — 解析 &lt;think&gt;/&lt;answer&gt; 标签

### Task 19: 补齐 tools/frame_extract.py

**审计:** 当前 1/2 = 50%
**目标:** 2/2 = 100%

- [ ] **19.1** `has_nvidia_gpu()` — nvidia-smi 检测 (subprocess)

### Task 20: 补齐 api/

**审计:** 当前 2/7 = 29%
**目标:** 4/7 = 57%

- [ ] **20.1** `video_upload_url.py` — 视频上传接口
- [ ] **20.2** `video_search_ingest.py` — 视频检索录入接口

---

## Phase C: 新 Agent 实现 (原 Plan Tasks 11-13)

### Task 11: Summary Agent (长视频摘要)

**Files:**
- Create: tests/unit/agents/test_summary_agent.py
- Create: src/vsa_agent/agents/summary_agent.py

**Learning:** 长视频分片策略、VLM聚合、安全报告生成

- [ ] **Step 1: Write test with mock VLM**
- [ ] **Step 2: Implement chunk → caption → aggregate → report pipeline**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

### Task 12: Critic Agent (自检环)

**Files:**
- Create: tests/unit/agents/test_critic_agent.py
- Create: src/vsa_agent/agents/critic_agent.py

**Learning:** 自检环、LLM评估

- [ ] **Step 1: Write test — Critic must reject incomplete reports**
- [ ] **Step 2: Implement safety checklist validator**
- [ ] **Step 3: Run tests → pass**
- [ ] **Step 4: Commit**

### Task 13: Postprocessing管线

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

## Phase D: 融合算法补齐 (P1)

### Task 21: fusion_search_rerank()

- [ ] **21.1** `_apply_weighted_linear_fusion()` — w_embed * embed + w_attribute * attribute
- [ ] **21.2** `_apply_rrf_fusion()` — 1/(rank + k) + w * norm_attr_score
- [ ] **21.3** `fusion_search_rerank()` — 整合调用上述融合 + attribute search + vst
- [ ] **21.4** `attribute_result_to_search_result()` — 属性搜结果 → SearchResult 转换

---

## 完成率约束

每个 task 完成后报告:
```
Search模块完成率: N/61 = P% (本task: +M项)
全项目完成率: N/93 = P%
```

跟踪文档: docs/superpowers/reviews/

---

> 更新日期: 2026-06-08 (审计后重排)
> 当前: Phase A (Task 14 开始)
