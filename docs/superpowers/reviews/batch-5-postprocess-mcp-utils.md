# Batch 5 审查 — 后处理 + MCP + Utils

> 审查日期: 2026-06-08
> vsa: `src/vsa_agent/` / NVIDIA: `_nvidia-original/agent/src/vss_agents/`
> 判定: ✅一致 / ⚠️简化有差距 / ❌缺失 / —框架差异不适用

---

## 1. agents/postprocess/ — vsa 独占, NVIDIA 无独立模块

NVIDIA: 无 `agents/postprocess/` 目录。后处理逻辑嵌入在 `top_agent._postprocessing_node` 中。

vsa: 独立模块, 4 文件, 3 个 validator + 1 个 pipeline。

### 结构

| 文件 | 类/函数 | 功能 |
|------|---------|------|
| `validators/base.py` | `ValidatorResult` + `BaseValidator` ABC | 验证结果模型 + 抽象基类 |
| `validators/non_empty.py` | `NonEmptyValidator` | 非空检查 |
| `validators/url_check.py` | `URLValidator` | URL 有效性检查 |
| `validators/safety_checklist.py` | `SafetyChecklistValidator` | 安全清单检查 |
| `pipeline.py` | `PostprocessingResult` + `ValidationPipeline` | 顺序执行, 首个失败即停止 |

### 设计评价

```
PostprocessingResult:  passed: bool
                       issues: list[str]   ← 缺少 (见 batch-1,但这是ValidatorResult的字段)
ValidationPipeline:    sequential, stop-on-first-fail
                       Dependency injection (validators list in __init__)
                       ✅ 干净的设计,易于扩展
```

> **判定: ✅ 完整且设计良好。** vsa 的后处理抽象比 NVIDIA 的内联方式更模块化。三个 validator 覆盖了基本需求(非空/URL/安全),添加新 validator 只需实现 `BaseValidator`。

**待办:**
- P3: `PostprocessingResult` 缺少 `issues` 字段(与 batch-1 的发现一致)


## 2. mcp/ — vsa 独占, NVIDIA 无 MCP 服务

NVIDIA: 无 MCP server。NVIDIA 通过 NAT 框架的 `custom_fastapi_worker.py` 暴露 REST API。

vsa: 独立 `mcp/server.py`，用 `fastmcp` 实现。

### 端点

| 工具名 | 功能 | 状态 |
|--------|------|------|
| `echo` | 回显消息 | ✅ |
| `list_tools` | 列出 MCP 可用工具 | ✅ |
| `chat` | 调用 top_agent 聊天 | ✅ |

### 工具暴露

```python
# 通过 ToolRegistry 暴露 vsa 工具给 MCP
for name, fn in ToolRegistry.get_all().items():
    mcp.tool(name=name, description=...)(fn)
```

> **判定: ✅ 完整且设计良好。** MCP server 提供了 REST API 之外的另一种协议选项。3个工具覆盖了基本调试+聊天功能。

**待办:** 无。


## 3. tools/ 周边

### 3.1 echo_tool.py — vsa 独占

| 函数 | 功能 | 状态 |
|------|------|------|
| `echo_tool(message)` | 回显消息, 注册为 `@register_tool("echo")` | ✅ |

> 开发调试用。**无待办。**

### 3.2 video_understanding.py (video_caption 合并)

已在 Batch 4 审查。vsa 将 NVIDIA 的 `video_understanding.py` + `video_caption.py` 两个文件合并为一个 `video_understanding.py`,功能对等。


## 4. utils/ — vsa 空模块 vs NVIDIA 12 个工具文件

### 4.1 NVIDIA utils 清单

| 文件 | 函数数 | 用途 | vsa 状态 |
|------|--------|------|---------|
| `asyncmixin.py` | 1类 | NAT 异步混入基类 | — 框架差异 |
| `file_mapping.py` | 2 | 文件名→key映射 | — P2 VST专用 |
| `frame_select.py` | 2 | 视频帧提取 | ✅ 见 Batch 4 |
| `markdown_parser.py` | 3 | Markdown解析 | ❌ 缺失 |
| `parser.py` | 4 | 通用JSON/XML解析 | ❌ 缺失 |
| `reasoning_parsing.py` | 3 | VLM推理trace解析 | ❌ 缺失 |
| `reasoning_utils.py` | 2 | 推理模式封装 | ❌ 缺失 |
| `retry.py` | 2 | 重试装饰器 | ❌ P1 |
| `time_convert.py` | 4 | 时间格式转换 | ❌ 缺失 |
| `time_measure.py` | 2 | 耗时测量 | ❌ 缺失 |
| `url_translation.py` | 3 | URL翻译(内外网) | — P2 VST/网络专用 |
| `video_file.py` | 3 | 视频文件处理 | — P2 VST专用 |

### 4.2 vsa utils/__init__.py — 空

> **vsa 的 utils/ 完全是空的。** 这是合理的——vsa 选择了"需要时再添加"策略。

### 4.3 哪些值得现在补齐?

| 优先级 | NVIDIA 文件 | 理由 |
|--------|-----------|------|
| **P1** | `retry.py` | model_adapter 的重试逻辑(batch-1 已有 P1 待办) |
| **P2** | `markdown_parser.py` | search_agent 输出格式化时可能需要 |
| **P2** | `time_convert.py` | ISO↔datetime 转换,当前硬编码在各处 |
| **P3** | `parser.py` | 通用解析,已有 `_get_json_from_string` 盖了主要场景 |
| **P3** | `reasoning_parsing.py` | VLM推理,当前 `_parse_thinking_from_content` 已盖 |
| **P3** | `reasoning_utils.py` | 推理模式,暂不需要 |
| **P3** | `time_measure.py` | 性能测量,logging 已盖基本需求 |
| — | `asyncmixin.py` | NAT框架专用 |
| — | `file_mapping.py` | VST专用 |
| — | `url_translation.py` | VST/网络专用 |
| — | `video_file.py` | VST专用 |

> **核心发现: 12个NVIDIA utils中,只有 `retry.py` 是 P1。** 其余要么框架差异,要么VST专用,要么已有等价实现。

### 4.4 vsa 已有的零散工具函数

| 函数 | 位置 | 等价 NVIDIA |
|------|------|-----------|
| `_parse_thinking_from_content()` | video_understanding.py | `reasoning_parsing.py` |
| `_get_json_from_string()` | critic_agent.py | `parser.py` (部分) |
| `_deduplicate_by_video_name()` | attribute_search.py | `_deduplicate_by_object()` |
| `_resolve_search_callable()` | search.py | `Builder.get_function()` |

> 这些函数分散在各模块中,而非集中在 utils/。**P2: 可统一到 utils/ 下。**


## 5. Batch 5 总结

### 判定矩阵

| 模块 | 评级 | 差距 |
|------|------|------|
| agents/postprocess/ | ✅ 完整 | P3: PostprocessingResult.issues |
| mcp/ | ✅ 完整 | — |
| echo_tool.py | ✅ | — |
| utils/ | ⚠️ 空模块 | P1: retry.py, P2: markdown_parser/time_convert |

### 所有待办

```
P1 (1项):
  [ ] utils/retry.py — 重试装饰器

P2 (2项):
  [ ] utils/markdown_parser.py
  [ ] utils/time_convert.py
  [ ] 分散的零散函数统一到 utils/

P3 (4项):
  [ ] PostprocessingResult.issues 字段
  [ ] utils/parser.py
  [ ] utils/reasoning_parsing.py
  [ ] utils/reasoning_utils.py
```

### 关键发现

1. **postprocess 和 MCP 都是 vsa 的改进** — NVIDIA 无独立模块,vsa 抽象更清晰
2. **utils/ 是唯一缺少基础设施的地方** — 只有 1 个 P1(retry)
3. **大量 NVIDIA utils 是 VST/ES 专用** — vsa 当前不需要
4. **vsa 的零散工具函数分布在业务模块中** — 功能对等,只是组织方式不同


## 全 5 批次合成 — 项目总览

### 各批次待办汇总

| 批次 | 范围 | P0 | P1 | P2 | P3 |
|------|------|-----|-----|-----|-----|
| Batch 1 | 基础设施 | 0 | 2 | 5 | 0 |
| Batch 2 | 搜索工具链 | 6 | 11 | 18 | 5 |
| Batch 3 | Agent 层 | 0 | 3 | 7 | 0 |
| Batch 4 | 视频+API | 0 | 1 | ~50 | 3 |
| Batch 5 | 后处理+MCP+utils | 0 | 1 | 3 | 4 |
| **合计** | | **6** | **18** | **~83** | **12** |

### 按优先级的行动路线

```
Phase D (当前 — Task 21):
  6 个 P0 融合函数 (search.py)

Phase E (下一阶段):
  18 个 P1 项:
    - 3 个 SearchAgentInput 字段
    - 2 个 model_adapter (error_message + retry)
    - 6 个 attribute_search P1 函数
    - 3 个 search.py P1 函数
    - 1 个 _build_vlm_messages
    - 2 个 SearchInput 字段 (min_cosine_similarity, use_critic)
    - 1 个 utils/retry.py

Phase F (后续 — ES/VST对接时):
  83 个 P2 项 (大部分是Config字段、ES操作、VST API)
```

### 模块完成率

| 模块 | 评级 | P0+P1 待办 |
|------|------|-----------|
| agents/data_models.py | ✅ 100% | 1 (error_message) |
| registry.py | ✅ 100% | 0 |
| config.py | ✅ 100% | 0 |
| model_adapter/ | ✅ 100% | 1 (retry) |
| agents/critic_agent.py | ✅ 100% | 0 |
| agents/summary_agent.py | ✅ 100% | 0 |
| agents/top_agent.py | ✅ 100% | 0 |
| agents/postprocess/ | ✅ 100% | 0 |
| mcp/ | ✅ 100% | 0 |
| tools/frame_extract.py | ✅ 100% | 0 |
| tools/embed_search.py | ✅ 89% | 0 |
| agents/search_agent.py | ⚠️ 67% | 3 (SearchAgentInput字段) |
| tools/search.py | ⚠️ 50% | 9 (6融合+3其他) |
| tools/attribute_search.py | ⚠️ 35% | 6 |
| tools/video_understanding.py | ⚠️ 可用 | 1 (_build_vlm_messages) |
| tools/query_builders.py | — P2 | 0 (暂不需要) |
| tools/vector_store.py | ⚠️ 占位 | 0 (ES对接时替换) |
| api/ | ⚠️ 简化 | 0 (核心端点完整) |
| utils/ | ⚠️ 空 | 1 (retry) |
