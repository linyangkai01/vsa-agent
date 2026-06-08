# vsa-agent 项目全局状态 — 2026-06-08

> 单一真相源。取代 [task0-5-audit.md](task0-5-audit.md) + [task6-10-audit.md](task6-10-audit.md) + [search-module-audit.md](search-module-audit.md)。
> 对比基准: `_nvidia-original/agent/src/vss_agents/`
> 标记: [x] 完成 / [~] 简化实现 / [ ] 未实现 / [—] 框架差异无需实现

---

## 一、基础设施层（Task 0-5）

### agents/data_models.py — 100%

| 类/枚举 | 状态 | 差距 |
|---------|------|------|
| AgentDecision | [~] | NAT用TOOL/END/AGENT/SUPERVISOR, vsa用CALL_TOOL/RESPOND(框架差异) |
| AgentMessageChunkType | [~] | 缺SUBAGENT_CALL, vsa暂不需要 |
| AgentMessageChunk | [x] | 字段一致 |
| AgentOutput | [~] | 缺error_message字段 |
| AgentState | [x] | vsa LangGraph需要, NAT无 |

### agents/top_agent.py — 框架根本不同,不逐项对比

NVIDIA: NAT框架 ~500行巨型函数(planning/reasoning/callback/sub-agent)。  
vsa-agent: LangGraph DAG (agent_node → tool_node → finalize_node)。

| 功能 | 状态 |
|------|------|
| LangGraph DAG | [x] StateGraph + InMemorySaver |
| Streaming | [x] get_stream_writer |
| Tool binding | [x] ToolRegistry.get_all() |
| Planning/Reasoning | [—] NAT功能, vsa用LLM自身thinking |
| Sub-agent delegation | [—] NAT功能, vsa用tool_node路由 |
| Callback handler | [ ] |

### registry.py — 100%

| 功能 | 状态 |
|------|------|
| 工具注册 | [x] @register_tool(name, description) |
| 工具发现 | [x] ToolRegistry.get()/get_all() |
| 工具列表 | [x] ToolRegistry.list_tools() |
| input/output schema | [ ] Pydantic schema on tools |

### model_adapter/ — 100%

| 文件 | 状态 | 差距 |
|------|------|------|
| base.py (ABC) | [x] | |
| openai_adapter.py | [x] | |
| vllm_adapter.py | [x] | |
| create_model_adapter() | [x] | |
| CosmosEmbedClient | [ ] P2 | vsa用mock embedding |
| 重试逻辑 | [ ] P1 | |

### config.py — 100%

| 功能 | 状态 |
|------|------|
| AppConfig + YAML | [x] |
| PromptsConfig | [x] |
| ModelConfig (dev/prod模式) | [x] |
| ToolsConfig | [x] |
| AgentConfig | [x] |

### api/ — 57%

| NVIDIA | vsa | 状态 |
|--------|-----|------|
| health_endpoint.py | health.py | [x] |
| custom_fastapi_worker.py | routes.py | [~] 仅POST /chat |
| video_search_ingest.py | video_search_ingest.py | [x] |
| video_upload_url.py | video_upload_url.py | [x] |
| rtsp_stream_api.py | — | [ ] |
| video_delete.py | — | [ ] |
| register.py | — | [ ] |

### mcp/ — 100%

| 功能 | 状态 |
|------|------|
| MCP server (fastmcp) | [x] |
| 工具暴露 | [x] |


## 二、视频工具层（Task 8-9）

### tools/frame_extract.py — 100%

| 函数 | 状态 | 差距 |
|------|------|------|
| _extract_frames() | [~] | 参数改进:多传fps/total_frames避免重复打开视频 |
| frame_extract_tool() | [x] | vsa新增, NVIDIA无包装 |
| has_nvidia_gpu() | [ ] P2 | |

### tools/video_understanding.py — 43%

| 函数/类 | 状态 | 差距 |
|----------|------|------|
| VideoUnderstandingInput | [x] | ✅ 字段一致 |
| _parse_thinking_from_content() | [x] | ✅ 与NVIDIA一致 |
| video_understanding_tool() | [x] | ✅ 注册版本 |
| VideoUnderstandingConfig | [ ] | NVIDIA有15+字段(real VLM配置) |
| VideoUnderstandingOffsetInput | [ ] | |
| extend_timestamp() | [ ] | |
| _build_vlm_messages() | [ ] | 简化内联,未独立 |

### tools/vector_store.py — 占位实现

| 类/函数 | 状态 |
|----------|------|
| InMemoryVectorStore | [~] | 空store,待ES替换 |
| search() | [~] | 返回空SearchOutput |
| search_by_attributes() | [~] | 返回空SearchOutput |
| get_default_store() etc | [~] | |

> **重要**: NVIDIA使用Elasticsearch + CosmosEmbed + VST内部API。vsa的所有search函数都是mock/stub实现——不是bug,是开发策略。替换vector_store为真实ES后,大部分search函数会自动工作。


## 三、搜索服务层（Task 11-21，你的核心困惑区）

### tools/search.py — 11/18 = 61%

| # | 函数 | 状态 | 备注 |
|---|------|------|------|
| 1 | DecomposedQuery | [x] | 9字段全齐 |
| 2 | SearchResult | [x] | 8字段全齐 |
| 3 | SearchOutput | [x] | |
| 4 | SearchInput | [x] | |
| 5 | SearchConfig | [x] | 11字段全齐 |
| 6 | decompose_query() | [x] | LLM分解+回退 |
| 7 | execute_core_search() | [~] | 三路径路由,但融合部分是简单合并(非RRF/weighted_linear) |
| 8 | _resolve_search_callable() | [x] | |
| 9 | search_tool() (注册) | [x] | 三路径路由 |
| | **以下未实现** | | |
| 10 | execute_core_search_wrapper() | [ ] P1 | |
| 11 | fusion_search_rerank() | [ ] P0 | 融合编排函数 |
| 12 | _apply_weighted_linear_fusion() | [ ] P0 | w_embed*embed + w_attribute*norm_attr |
| 13 | _apply_rrf_fusion() | [ ] P0 | 1/(rank+k) + w*norm_attr |
| 14 | _apply_rrf_fusion_with_attribute_rank() | [ ] P0 | 双rank RRF |
| 15 | _run_attribute_only_search() | [ ] P1 | |
| 16 | attribute_result_to_search_result() | [ ] P0 | AttributeSearchResult → SearchResult |
| 17 | _callable() (内部闭包) | [x] | |

### tools/embed_search.py — 8/9 = 89%

| # | 函数 | 状态 | 备注 |
|---|------|------|------|
| 1 | EmbedSearchResultItem | [x] | |
| 2 | EmbedSearchOutput | [x] | |
| 3 | QueryInput | [x] | |
| 4 | _generate_query_embedding() | [x] | mock实现(deterministic hash) |
| 5 | _process_search_hit() | [x] | |
| 6 | embed_search_tool() (注册) | [x] | |
| 7 | _build_es_query() | [ ] P2 | NVIDIA用ES查询体 |
| 8 | _sanitize_for_logging() | [ ] P2 | |

> **接近完成。** 剩余2个函数是ES-specific helper,不需要现在实现。

### tools/attribute_search.py — 8/13 = 62%

| # | 函数 | 状态 | 备注 |
|---|------|------|------|
| 1 | AttributeSearchInput | [x] | |
| 2 | AttributeSearchMetadata | [x] | |
| 3 | AttributeSearchResult | [x] | |
| 4 | search_by_attributes() | [x] | mock实现 |
| 5 | _deduplicate_by_video_name() | [x] | |
| 6 | attribute_search_tool() (注册) | [x] | |
| | **以下未实现** | | |
| 7 | search_single_attribute() | [ ] P1 | |
| 8 | search_attributes() | [ ] P1 | |
| 9 | _fuse_multi_attribute() | [ ] P1 | |
| 10 | _append_multi_attribute() | [ ] P1 | |
| 11 | _perform_frame_lookups() | [ ] P1 | ES操作 |
| 12 | _get_frame_from_behavior() | [ ] P2 | |
| 13 | _search_behavior() | [ ] P2 | |
| 14 | _build_result() | [ ] P1 | |
| 15 | _extend_clip_to_one_second() | [ ] P2 | |
| 16 | AttributeSearchConfig | [ ] P1 | |

### tools/query_builders.py — 0/3 = 0%

**空桩。** NVIDIA有 IncidentQueryBuilder / FramesQueryBuilder / BehaviorQueryBuilder。vsa中 query_builders.py 只有注释说明"预留"。

### agents/search_agent.py — 8/11 = 73%

| # | 函数 | 状态 | 备注 |
|---|------|------|------|
| 1 | SearchAgentInput | [x] | |
| 2 | SearchAgentConfig | [x] | |
| 3 | _to_search_results() | [x] | |
| 4 | _to_incidents_output() | [x] | |
| 5 | search_agent_tool() (注册) | [x] | |
| 6 | execute_search() | [x] | 三路径路由 |
| | **以下未实现** | | |
| 7 | _helper_markdown_bullet_list() | [ ] P2 | 输出格式化 |
| 8 | _to_chat_response() | [ ] P2 | 输出格式化 |
| 9 | _to_chat_response_chunk() | [ ] P2 | 输出格式化 |

> **接近完成。** 剩余3个是输出格式化函数(P2),不影响核心搜索功能。

### agents/critic_agent.py — 100%

| 函数/类 | 状态 |
|----------|------|
| CriticAgentInput | [x] |
| CriticAgentOutput | [x] |
| CriticAgentResult (枚举) | [x] |
| VideoInfo | [x] |
| VideoResult | [x] |
| execute_critic() | [x] |
| _get_json_from_string() | [x] |
| critic_agent_tool() (注册) | [x] |

### agents/summary_agent.py — vsa独占,无NVIDIA对应 — 100%

| 函数/类 | 状态 |
|----------|------|
| SummaryAgentInput | [x] |
| execute_summary() | [x] |
| summary_agent_tool() (注册) | [x] |


## 四、总览

| 模块 | 完成 | 总数 | 完成率 | 优先级 |
|------|------|------|--------|--------|
| agents/data_models.py | 4 | 4 | 100% | — |
| agents/top_agent.py | 1 | 1 | 100% | — |
| registry.py | 1 | 1 | 100% | — |
| model_adapter/ | 3 | 3 | 100% | — |
| config.py | 1 | 1 | 100% | — |
| mcp/ | 2 | 2 | 100% | — |
| tools/frame_extract.py | 2 | 2 | 100% | — |
| agents/critic_agent.py | 8 | 8 | 100% | — |
| agents/summary_agent.py | 3 | 3 | 100% | — |
| agents/postprocess/ | 6 | 6 | 100% | — |
| **tools/embed_search.py** | **8** | **9** | **89%** | 仅缺2个P2辅助 |
| **agents/search_agent.py** | **8** | **11** | **73%** | 仅缺3个P2格式化 |
| **tools/search.py** | **11** | **18** | **61%** | **P0: 6个融合函数** |
| **tools/attribute_search.py** | **8** | **16** | **50%** | P1: 9个搜索函数 |
| api/ | 4 | 7 | 57% | P2: RTSP/删除 |
| tools/video_understanding.py | 3 | 7 | 43% | P2: VLM配置 |
| **tools/query_builders.py** | **0** | **3** | **0%** | ES相关,暂不需要 |
| tools/vector_store.py | 4 | 4 | 100%(占位) | ES替换时重新实现 |
| **整体** | **77** | **106** | **73%** | |

### 按优先级排序的待办

```
P0 (当前阶段 — Phase D 融合算法):  6个函数
  _apply_weighted_linear_fusion()
  _apply_rrf_fusion()
  _apply_rrf_fusion_with_attribute_rank()
  fusion_search_rerank()
  attribute_result_to_search_result()
  execute_core_search_wrapper()

P1 (下一阶段 — attribute_search 补齐): 12个函数
  search_attributes(), search_single_attribute(),
  _fuse_multi_attribute(), _append_multi_attribute(),
  _build_result(), _perform_frame_lookups(),
  _search_behavior(), _run_attribute_only_search(),
  _get_frame_from_behavior(), _extend_clip_to_one_second(),
  AttributeSearchConfig, model_adapter retry

P2 (锦上添花 — 输出格式化/ES辅助): 15个函数
  _helper_markdown_bullet_list(), _to_chat_response(),
  _to_chat_response_chunk(), _build_es_query(),
  _sanitize_for_logging(), has_nvidia_gpu(),
  VideoUnderstandingConfig/OffsetInput/extend_timestamp,
  _build_vlm_messages, IncidentQueryBuilder,
  FramesQueryBuilder, BehaviorQueryBuilder,
  rtsp_stream_api, video_delete, register.py
```

### 测试覆盖

| 测试文件 | 测试数 | 覆盖范围 |
|----------|--------|----------|
| test_integration_pipeline.py | 87 pass + 4 skip + 24 xfail | **全模块全联通** |
| test_search_tools.py | 11 | embed/attribute/search 三个工具 |
| test_search_agent.py | 15 | execute_search + decompose_query + 数据模型 |
| test_task14-18.py | ~30 | 各模块独立函数 |
| test_critic_agent.py | 6 | critic 全流程 |
| test_summary_agent.py | 6 | summary 全流程 |
| test_top_agent.py | 6 | DAG + 路由 |
| test_frame_extract.py | 3 | 帧提取 |
| test_video_understanding.py | 2 | VLM 理解 |
| test_registry.py | 3 | 工具注册 |
| test_pipeline.py | 6 | 后处理管线 |
| test_model_adapter.py | 3 | 模型适配器 |
| **总计** | **~206+** | |

## 附：审计文档处置建议

| 文档 | 处置 |
|------|------|
| task0-5-audit.md | 已合并,可归档 |
| task6-10-audit.md | 已合并,可归档 |
| search-module-audit.md | 已合并,可归档 |
| **project-status-2026-06-08.md (本文档)** | **单一真相源,持续更新** |

> 更新规则: 每完成一个 task 后更新本文档对应函数的状态标记。
