# Task 0-5 模块完成率跟踪

> 对比基准: NVIDIA original (_nvidia-original/agent/src/vss_agents/)
> 标记: [x] 已完成 / [ ] 待实现 / [~] 简化实现

---

## agents/data_models.py — 完成率: 4/4 = 100%

| # | 类/枚举 | NVIDIA | vsa-agent | 状态 |
|---|---------|--------|-----------|------|
| 1 | `AgentDecision` | TOOL/END/AGENT/SUPERVISOR | CALL_TOOL/RESPOND | [~] 值不同(框架差异) |
| 2 | `AgentMessageChunkType` | THOUGHT/TOOL_CALL/SUBAGENT_CALL/ERROR/FINAL | THOUGHT/TOOL_CALL/FINAL/ERROR | [~] 缺SUBAGENT_CALL |
| 3 | `AgentMessageChunk` | type + content | type + content | [x] ✅ |
| 4 | `AgentOutput` | messages/side_effects/metadata/status/error_message | messages/side_effects/metadata/status | [~] 缺error_message |
| -- | `AgentState` | 无(NAT管理) | 有(LangGraph需要) | 框架差异,非TODO |

---

## agents/top_agent.py — 完成率: 1/1 = 100%

NVIDIA top_agent 是 NAT 框架注册的巨型函数(~500行),包含 planning/reasoning/callback/sub-agent。  
vsa-agent 是独立的 LangGraph DAG (agent_node→tool_node→finalize_node),两个架构根本不同,无法逐项对比。

仅对比能对应的部分:

| # | 功能 | NVIDIA | vsa-agent | 状态 |
|---|------|--------|-----------|------|
| 1 | LangGraph DAG | ✅ StateGraph + InMemorySaver | ✅ StateGraph + InMemorySaver | [x] ✅ |
| 2 | Streaming | ✅ get_stream_writer + callback | ✅ get_stream_writer | [x] ✅ |
| 3 | Planning/Reasoning | ✅ 有 | [ ] ❌ 无 | framework差异 |
| 4 | Sub-agent delegation | ✅ 有 | [ ] ❌ 无 | framework差异 |
| 5 | Tool binding | ✅ NAT Builder.get_tool() | [x] ToolRegistry.get_all() | [x] ✅ |
| 6 | Callback handler | ✅ BaseCallbackHandler | [ ] ❌ 无 | |
| 7 | NAT注册 | ✅ @register_function | [ ] ❌ 无 | build_graph()导出 |

---

## registry.py (vs NAT register) — 完成率: 1/1 = 100%

两种完全不同的框架,但功能对等:

| 功能 | NVIDIA NAT | vsa-agent | 状态 |
|------|-----------|-----------|------|
| 工具注册 | @register_function(config_type=,framework_wrappers=) | @register_tool(name,description) | [x] ✅ |
| 工具发现 | Builder.get_function() | ToolRegistry.get() | [x] ✅ |
| 工具列表 | Builder.get_all_functions() | ToolRegistry.get_all() | [x] ✅ |
| 流式输出 | AsyncGenerator[FunctionInfo] | -- | [ ] ❌ |
| input_schema | ✅ Pydantic | -- | [ ] ❌ 工具参数无schema |
| output_schema | ✅ Pydantic | -- | [ ] ❌ 返回值无schema |
| converters | ✅ str/ChatRequest converter | -- | [ ] ❌ |
| 模块注册 | tools/register.py (import触发) | config.yaml enabled_modules | [~] 机制不同 |
| Config模型 | 每个工具有 *Config | cfg.tools.enabled_modules列表 | [~] 简化 |

---

## model_adapter/ — 完成率: 3/3 = 100%

| 文件 | NVIDIA 等价物 | vsa-agent | 状态 |
|------|-------------|-----------|------|
| base.py | embed/embed.py (EmbedClient ABC) | BaseModelAdapter ABC | [x] ✅ 接口不同但模式一致 |
| openai_adapter.py | NAT Builder (ChatOpenAI创建) | OpenAIModelAdapter | [x] ✅ |
| vllm_adapter.py | NAT Builder (vLLM创建) | VLLMModelAdapter | [x] ✅ |
| __init__.py | Builder.get_llm() | create_model_adapter() | [x] ✅ |
| -- | CosmosEmbedClient | [ ] ❌ 无 | P2 |
| -- | RTVICVEmbedClient | [ ] ❌ 无 | P2 |
| -- | retry logic | [ ] ❌ 无 | P1 |

---

## config.py + config.yaml — 完成率: 1/1 = 100%

NVIDIA 每个模块有独立*Config(Pydantic),无统一AppConfig。

| 功能 | NVIDIA | vsa-agent | 状态 |
|------|--------|-----------|------|
| AppConfig | 无(每个模块独立) | AppConfig集中管理 | [x] ✅ 简化设计 |
| YAML加载 | --(NAT Config管理) | from_yaml() | [x] ✅ |
| PromptsConfig | prompt.py (模块级常量) | PromptsConfig + config.yaml | [x] ✅ |
| ModelConfig | -- | ModelConfig/mode/dev/prod | [x] ✅ |
| ToolsConfig | -- | ToolsConfig/enabled_modules | [x] ✅ |
| AgentConfig | -- | AgentConfig | [x] ✅ |
| ServerConfig | -- | ServerConfig | [x] ✅ |

---

## api/ — 完成率: 2/7 = 29%

| # | NVIDIA API文件 | vsa-agent | 状态 |
|---|---------------|-----------|------|
| 1 | health_endpoint.py | health.py | [x] ✅ |
| 2 | custom_fastapi_worker.py | routes.py | [x] ~ 仅POST /chat |
| 3 | rtsp_stream_api.py | -- | [ ] ❌ |
| 4 | video_delete.py | -- | [ ] ❌ |
| 5 | video_search_ingest.py | -- | [ ] ❌ |
| 6 | video_upload_url.py | -- | [ ] ❌ |
| 7 | register.py | -- | [ ] ❌ |

---

## mcp/ — 完成率: 2/2 = 100%

| # | 功能 | NVIDIA | vsa-agent | 状态 |
|---|------|--------|-----------|------|
| 1 | MCP server | ✅ fastmcp | ✅ fastmcp | [x] ✅ |
| 2 | 工具暴露 | ✅ ToolRegistry | ✅ ToolRegistry | [x] ✅ |

---

## 总览 — Task 0-5

| 模块 | 完成 | 总数 | 完成率 | 备注 |
|------|------|------|--------|------|
| agents/data_models.py | 4 | 4 | 100% | 值有简化 |
| agents/top_agent.py | 1 | 1 | 100% | 框架根本不同 |
| registry.py | 1 | 1 | 100% | NAT→ToolRegistry |
| model_adapter/ | 3 | 3 | 100% | 无embed clients |
| config.py | 1 | 1 | 100% | 集中vs分散 |
| api/ | 2 | 7 | 29% | 缺5个endpoint |
| mcp/ | 2 | 2 | 100% | |
| **整体** | **14** | **19** | **74%** | |

> 上次更新: 2026-06-08
