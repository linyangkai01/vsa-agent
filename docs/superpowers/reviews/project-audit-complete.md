# vsa-agent 完整审查报告 — 2026-06-08

> 对比基准: NVIDIA original (`_nvidia-original/agent/src/vss_agents/`)
> 审查方法: 5批次逐模块、逐字段、逐函数对比
> 批次文档: [batch-1](batch-1-infrastructure.md) / [batch-2](batch-2-search-tools.md) / [batch-3](batch-3-agents.md) / [batch-4](batch-4-video-api.md) / [batch-5](batch-5-postprocess-mcp-utils.md)
> 标记: ✅一致 / ⚠️简化 / ❌缺失 / —框架差异

---

## 总体状态

| 指标 | 值 |
|------|-----|
| NVIDIA 函数/类总数 | ~180 |
| vsa 已实现 | ~95 |
| 数据模型字段匹配率 | 91/94 = 97% |
| 核心功能完成率 | ~85% |
| P0 待办 (阻塞) | 6 |
| P1 待办 (应尽快) | 18 |
| P2 待办 (后续优化) | ~83 |

---

## 模块一览

### ✅ 100% 完成 (11/19 模块)

| 模块 | 说明 |
|------|------|
| `agents/data_models.py` | 4/4 类, 缺 error_message (P1) |
| `registry.py` | 工具注册/发现/列表 5/5 功能 |
| `config.py` | AppConfig + 6 子配置 |
| `model_adapter/` | 3 个适配器 + 工厂函数, 缺 retry (P1) |
| `agents/critic_agent.py` | 6 模型 + 3 核心函数, 100% 匹配 |
| `agents/summary_agent.py` | vsa 独占, 设计良好 |
| `agents/top_agent.py` | 10/10 State 字段, 核心循环对等 |
| `agents/postprocess/` | 3 validator + pipeline, vsa 改进 |
| `mcp/` | fastmcp server, vsa 独占 |
| `tools/frame_extract.py` | 帧提取, 参数改进 |
| `tools/echo_tool.py` | 调试工具 |

### ⚠️ 有差距 (5/19 模块)

| 模块 | 完成率 | P0 | P1 | 最大差距 |
|------|--------|-----|-----|---------|
| `tools/embed_search.py` | 89% | 0 | 0 | 仅缺 ES helper (P2) |
| `agents/search_agent.py` | 67% | 0 | 3 | SearchAgentInput 缺 3 字段 |
| `tools/search.py` | 50% | 6 | 3 | **融合算法全部缺失** |
| `tools/attribute_search.py` | 35% | 0 | 6 | multi-attribute 搜索 |
| `tools/video_understanding.py` | 50% | 0 | 1 | VLM 配置 (P2) |

### — 暂不需要 (3/19 模块)

| 模块 | 说明 |
|------|------|
| `tools/query_builders.py` | ES 查询构建器, 对接 ES 时实现 |
| `tools/vector_store.py` | InMemory 占位, 对接 ES 时替换 |
| `utils/` | 空模块, 仅缺 retry (P1) |

---

## 按优先级行动路线

### Phase D — 当前 (6 个 P0)
```
tools/search.py:
  _apply_weighted_linear_fusion()
  _apply_rrf_fusion()
  _apply_rrf_fusion_with_attribute_rank()
  fusion_search_rerank()
  attribute_result_to_search_result()
  _run_attribute_only_search()
```

### Phase E — 下一阶段 (18 个 P1)
```
数据模型补齐:
  AgentOutput.error_message
  SearchAgentInput.use_attribute_search
  SearchAgentInput.source_type
  SearchAgentInput.use_critic
  SearchInput.min_cosine_similarity
  SearchInput.use_critic

核心函数补齐:
  model_adapter retry 逻辑
  execute_core_search_wrapper()
  search_single_attribute()
  search_attributes()
  _fuse_multi_attribute()
  _append_multi_attribute()
  _build_result()
  _build_vlm_messages() 独立函数
  utils/retry.py

其他:
  _to_search_results Pydantic model_dump 支持
  critic 并行验证 (asyncio.gather)
```

### Phase F — 后续 (83 个 P2)
```
ES/VST 对接:
  query_builders (3 类 6 函数)
  vector_store → ES 替换
  SearchConfig/EmbedSearchConfig/AttributeSearchConfig (30+ 字段)
  _perform_frame_lookups, _search_behavior 等 ES 操作

VLM 配置:
  VideoUnderstandingConfig (20 字段)
  流式 VLM 输出
  extend_timestamp, offset 模式

API 完善:
  RTSP stream API (22 函数)
  Video delete API (7 函数)
  WebSocket /chat
  MinIO presigned URL

输出格式化:
  _helper_markdown_bullet_list, _to_chat_response, _to_chat_response_chunk
  _execute_search_stream

工具组织:
  分散的零散函数统一到 utils/
  utils/markdown_parser, time_convert, parser
```

---

## 测试覆盖

| 测试文件 | 测试数 |
|----------|--------|
| test_integration_pipeline.py | 87 pass + 4 skip + 24 xfail |
| test_search_tools.py | 11 |
| test_search_agent.py | 15 |
| test_task14-18.py | ~30 |
| test_critic_agent.py, test_summary_agent.py | 12 |
| test_top_agent.py, test_frame_extract.py 等 | ~15 |
| test_registry.py, test_pipeline.py, test_model_adapter.py | ~12 |
| **总计** | **~206 pass + 24 xfail** |

---

## 审计文档清单

| 文档 | 状态 |
|------|------|
| `task0-5-audit.md` | 📦 已合并, 可归档 |
| `task6-10-audit.md` | 📦 已合并, 可归档 |
| `search-module-audit.md` | 📦 已合并, 可归档 |
| `project-status-2026-06-08.md` | 📦 已合并, 可归档 |
| `batch-1-infrastructure.md` | 📄 批次详情 |
| `batch-2-search-tools.md` | 📄 批次详情 |
| `batch-3-agents.md` | 📄 批次详情 |
| `batch-4-video-api.md` | 📄 批次详情 |
| `batch-5-postprocess-mcp-utils.md` | 📄 批次详情 |
| **`project-audit-complete.md`** | **⭐ 单一真相源** |
