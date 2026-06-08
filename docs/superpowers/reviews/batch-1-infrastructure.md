# Batch 1 审查 — 数据模型 + 基础设施

> 审查日期: 2026-06-08
> vsa: `src/vsa_agent/` / NVIDIA: `_nvidia-original/agent/src/vss_agents/`
> 判定: ✅一致 / ⚠️简化有差距 / ❌缺失 / —框架差异不适用

---

## 1. agents/data_models.py

### 1.1 AgentDecision (enum)

| 项目 | NVIDIA | vsa-agent | 判定 |
|------|--------|-----------|------|
| 基类 | `enum.StrEnum` | `enum.StrEnum` | ✅ |
| TOOL | `"tool"` | — | — |
| END | `"finished"` | — | — |
| AGENT | `"agent"` | — | — |
| SUPERVISOR | `"supervisor"` | — | — |
| CALL_TOOL | — | `"call_tool"` | — |
| RESPOND | — | `"respond"` | — |

> **判定: — (框架差异)**。NVIDIA用NAT框架的多Agent决策值(TOOL/END/AGENT/SUPERVISOR)，vsa用LangGraph的简单两路路由(CALL_TOOL/RESPOND)。不需对齐。

### 1.2 AgentMessageChunkType (enum)

| 项目 | NVIDIA | vsa-agent | 判定 |
|------|--------|-----------|------|
| 基类 | `enum.StrEnum` | `enum.StrEnum` | ✅ |
| THOUGHT | ✅ `"thought"` | ✅ `"thought"` | ✅ |
| TOOL_CALL | ✅ `"tool_call"` | ✅ `"tool_call"` | ✅ |
| SUBAGENT_CALL | ✅ `"subagent_call"` | ❌ 无 | — |
| ERROR | ✅ `"error"` | ✅ `"error"` | ✅ |
| FINAL | ✅ `"final"` | ✅ `"final"` | ✅ |

> **判定: — (框架差异)**。SUBAGENT_CALL是NVIDIA多Agent架构需要的，vsa无sub-agent。其余4个值完全一致。

### 1.3 AgentMessageChunk (Pydantic model)

| 字段 | NVIDIA类型 | NVIDIA默认值 | vsa类型 | vsa默认值 | 判定 |
|------|-----------|-------------|---------|----------|------|
| `type` | `AgentMessageChunkType` | `THOUGHT` | `AgentMessageChunkType` | `THOUGHT` | ✅ |
| `content` | `str` | `""` | `str` | `""` | ✅ |

> **判定: ✅ 完全一致。** 字段名/类型/默认值/语义完全匹配。

### 1.4 AgentOutput (Pydantic model)

| 字段 | NVIDIA类型 | NVIDIA默认值 | vsa类型 | vsa默认值 | 判定 |
|------|-----------|-------------|---------|----------|------|
| `messages` | `list[str]` | `[]` | `list[str]` | `[]` | ✅ |
| `side_effects` | `dict[str, Any]` | `{}` | `dict` | `{}` | ✅ |
| `metadata` | `dict[str, Any]` | `{}` | `dict` | `{}` | ✅ |
| `status` | `Literal["success","partial_success","error"]` | `"success"` | `str` | `"success"` | ⚠️ |
| `error_message` | `str \| None` | `None` | ❌ 缺失 | — | ❌ |

> **判定: ❌ 缺1个字段，⚠️ 1个字段类型弱化。**
> - `error_message`: **必要。** 当status="error"时承载错误详情。所有agent的异常路径依赖此字段。
> - `status`: vsa用普通`str`而非`Literal["success","partial_success","error"]`，丢失了类型安全。**P2: 改为Literal。**

### 1.5 AgentState (vsa独占，NVIDIA无)

| 字段 | 类型 | 必要性 |
|------|------|--------|
| `current_message` | `BaseMessage \| None` | LangGraph需要 |
| `agent_scratchpad` | `list[BaseMessage]` | LangGraph需要 |
| `conversation_history` | `list[BaseMessage]` | LangGraph需要 |
| `iteration_count` | `int` | LangGraph需要 |
| `final_answer` | `str` | LangGraph需要 |
| `plan` | `str` | 预留 |
| `previous_conversation` | `str` | 预留 |
| `llm_reasoning` | `bool` | 预留 |
| `vlm_reasoning` | `bool \| None` | 预留 |
| `search_source_type` | `str` | 预留 |

> **判定: — (框架差异)**。NVIDIA NAT管理状态，vsa LangGraph需要显式State。5个核心字段是必须的，5个预留字段暂时不用。

### data_models.py 小结

| 指标 | 值 |
|------|-----|
| NVIDIA 类/枚举 | 4 |
| vsa 实现 | 5 (含AgentState) |
| 字段完全一致 | AgentMessageChunk |
| 字段缺失 | AgentOutput.error_message |
| 字段弱化 | AgentOutput.status (str→Literal) |
| 框架差异不适用 | AgentDecision值, AgentMessageChunkType缺SUBAGENT_CALL, AgentState |

**待办:**
- ⚠️ P1: 添加 `AgentOutput.error_message: str | None = None`
- ⚠️ P2: `AgentOutput.status` 改为 `Literal["success","partial_success","error"]`


## 2. registry.py (vs NVIDIA agents/register.py + tools/register.py)

NVIDIA架构：NAT框架，`agents/register.py`和`tools/register.py`各是一组`import`语句触发`@register_function`装饰器。

vsa架构：自己实现的`ToolRegistry`类。

### 功能对比

| 功能 | NVIDIA (NAT) | vsa (ToolRegistry) | 判定 |
|------|-------------|-------------------|------|
| 工具注册 | `@register_function(config_type=..., framework_wrappers=...)` | `@register_tool(name, description)` | ✅ |
| 按名查找 | `Builder.get_function(name)` | `ToolRegistry.get(name)` | ✅ |
| 获取全部 | `Builder.get_all_functions()` | `ToolRegistry.get_all()` | ✅ |
| 工具列表+描述 | 通过FunctionInfo | `ToolRegistry.list_tools()` | ✅ |
| 模块懒加载 | `import`触发 | `_ensure_loaded()` + config.yaml | ✅ |
| Pydantic input schema | ✅ NAT自动生成 | — | ⚠️ |
| Pydantic output schema | ✅ NAT自动生成 | — | ⚠️ |
| 流式输出 | `AsyncGenerator[FunctionInfo]` | — | ⚠️ |
| 工具converters | ✅ str/ChatRequest converter | — | ⚠️ |

> **判定: ✅ 核心功能对等。** 注册/查找/列表/懒加载全部实现。
> 缺失的 schema/流式/converters 是 NAT 框架特性，vsa 暂不需要。
> **P2: 可为工具添加 optional `input_schema`/`output_schema` Pydantic model 用于文档和验证。**

### 注册表工具清单验证

| 工具名 | NVIDIA文件 | vsa文件 | 判定 |
|--------|-----------|---------|------|
| echo | — (vsa独占) | echo_tool.py | ✅ |
| embed_search | embed_search.py | embed_search.py | ✅ |
| attribute_search | attribute_search.py | attribute_search.py | ✅ |
| search | search.py | search.py | ✅ |
| search_agent | search_agent.py | search_agent.py | ✅ |
| summary_agent | — (vsa独占) | summary_agent.py | ✅ |
| critic_agent | critic_agent.py | critic_agent.py | ✅ |
| frame_extract | — (vsa独占) | frame_extract.py | ✅ |
| video_understanding | video_understanding.py | video_understanding.py | ✅ |

> 9个工具全部注册。vsa有3个独占工具(echo/frame_extract/summary_agent)，NVIDIA没有对应。

### registry.py 小结

| 指标 | 值 |
|------|-----|
| 核心功能匹配 | 5/5 |
| 高级功能 | 0/3 (P2, 暂不需要) |
| 注册工具数 | 9 (vs 7 NVIDIA) |

**待办:**
- ⚠️ P2: 可选：工具添加 Pydantic input/output schema


## 3. config.py

NVIDIA：无统一AppConfig。每个模块通过NAT Builder注入独立的`*Config` Pydantic model（如SearchConfig、VideoUnderstandingConfig等）。

vsa：集中式`AppConfig` + `config.yaml`。

### vsa AppConfig 结构

| 子配置 | 字段数 | 用途 |
|--------|--------|------|
| `PromptsConfig` | 4 | 全部prompt字符串 |
| `ModelConfig` (含dev/prod子模式) | 5+5 | LLM/VLM provider/model/base_url |
| `ToolsConfig` | 1 | 启用的工具模块列表 |
| `AgentConfig` | 5 | max_iterations, planning, postprocessing, log_level, max_history |
| `ServerConfig` | 2 | host, port |

> **判定: — (设计选择,非差距)。** NVIDIA的分散配置和vsa的集中配置是两种有效的架构风格。vsa的集中式更易于开发和调试。当需要对接真实ES/VST时，可以为对应模块追加独立Config。

**待办:**
- 无。


## 4. model_adapter/

### 4.1 对照关系

NVIDIA：`embed/EmbedClient` ABC — 嵌入客户端（image/text/video → vector）。  
vsa：`model_adapter/BaseModelAdapter` ABC — LLM/VLM适配器（messages → response）。

**两者目的不同，不是同类组件。** 以下分开审计：

### 4.2 NVIDIA EmbedClient → vsa 缺失

| NVIDIA | vsa | 判定 |
|--------|-----|------|
| `EmbedClient` ABC | 无 | — |
| `get_image_embedding(image_url) -> list[float]` | 无 | — |
| `get_text_embedding(text) -> list[float]` | 无 | — |
| `get_video_embedding(video_url) -> list[float]` | 无 | — |
| `CosmosEmbedClient` (HTTP实现) | 无 | — |
| `RTVICVEmbedClient` | 无 | — |

> **判定: — (当前阶段不需要)。** embed_search当前用mock vector_store (InMemoryVectorStore)，不依赖真实嵌入。当对接ES时需实现`EmbedClient`。

### 4.3 vsa BaseModelAdapter → NVIDIA 对应

NVIDIA的LLM调用通过NAT Builder（`Builder.get_llm()` → ChatOpenAI），无独立adapter抽象。vsa独立封装是改进。

| vsa组件 | 功能 | 判定 |
|---------|------|------|
| `BaseModelAdapter` ABC | `invoke()` + `astream()` | ✅ 设计良好 |
| `OpenAIModelAdapter` | ChatOpenAI封装, dev模式 | ✅ |
| `VLLMModelAdapter` | ChatOpenAI封装, prod模式 | ✅ |
| `create_model_adapter()` | 工厂函数, 按mode自动选择 | ✅ |

**缺失功能:**

| 功能 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| 重试逻辑 | ✅ NAT retry | ❌ | ⚠️ P1 |
| 超时控制 | ✅ NAT timeout | ❌ | ⚠️ P2 |
| VLM模式切换 | — | ❌ 硬编码ChatOpenAI | ⚠️ P2 |

> **判定: ✅ 核心功能完整。** LLM/VLM调用栈干净。缺重试逻辑是唯一P1项。

### model_adapter 小结

| 指标 | 值 |
|------|-----|
| LLM/VLM适配器 | 3/3 ✅ |
| 工厂函数 | ✅ |
| EmbedClient | 0/2 (P2, 暂不需要) |
| 重试逻辑 | ❌ P1 |
| 超时控制 | ❌ P2 |

**待办:**
- ⚠️ P1: 添加 retry 逻辑（ChatOpenAI支持`max_retries`参数）
- ⚠️ P2: 添加 timeout 控制
- ⚠️ P2: 后续实现 EmbedClient ABC + CosmosEmbedClient


## 5. Batch 1 总结

### 判定矩阵

| 组件 | 完全一致 | 需补齐 | 框架差异不适用 |
|------|---------|--------|---------------|
| data_models.py | 1/5 类 | AgentOutput缺error_message | AgentDecision值, AgentMessageChunkType缺SUBAGENT_CALL, AgentState |
| registry.py | 5/5 核心功能 | P2: tool schema | NAT框架机制 |
| config.py | — | 无 | 集中vs分散,风格选择 |
| model_adapter/ | 3/3 LLM适配器 | P1: retry, P2: EmbedClient | EmbedClient暂不需要 |

### 待办按优先级

```
P1 (应尽快实现):
  [ ] AgentOutput.error_message 字段
  [ ] model_adapter 重试逻辑

P2 (后续优化):
  [ ] AgentOutput.status 改为 Literal["success","partial_success","error"]
  [ ] ToolRegistry 支持可选的 Pydantic input/output schema
  [ ] model_adapter 超时控制
  [ ] EmbedClient ABC (对接真实ES时需要)
```
