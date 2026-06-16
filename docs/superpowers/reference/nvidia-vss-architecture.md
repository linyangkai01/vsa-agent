# NVIDIA VSS Architecture Reference (v1.0)

> 基于 `_nvidia-original/agent/src/vss_agents/` 的完整架构分析
> 目标: 为去 NVIDIA 依赖复现提供模块级参考
> 日期: 2026-06-09

---

## 一、整体架构概览

NVIDIA VSS (Video Surveillance System) Agents 是一个基于 **LangGraph** + **NAT (NeMo Agent Toolkit)** 的多 Agent 视频搜索与分析系统。

### 1.1 核心依赖（需要替代的 NVIDIA 组件）

| 依赖 | 作用 | 替代方案 |
|------|------|----------|
| `nat.*` (NeMo Agent Toolkit) | 函数注册、Builder、FunctionInfo、配置注入 | 自建 registry + config |
| `langchain` / `langgraph` | LLM 调用、Agent 图编排 | 保留（开源） |
| `elasticsearch` | 向量搜索 + 属性搜索 | 保留（开源） |
| `boto3` (MinIO) | S3 视频存储 | 保留（开源） |
| `aiohttp` | HTTP 客户端 | 保留（开源） |
| `CosmosEmbedClient` | NVIDIA 嵌入服务 | 替代为 OpenAI/开源嵌入 |
| `RTVICVEmbedClient` | NVIDIA 属性嵌入 | 替代为开源嵌入 |
| `VST` (Video Storage & Transfer) | 视频存储服务 | 替代为本地文件/MinIO |

### 1.2 包结构

```
vss_agents/
├── __init__.py              # 空（仅 license）
├── prompt.py                # 所有 prompt 常量
├── agents/                  # Agent 层
│   ├── __init__.py          # 空
│   ├── data_models.py       # AgentDecision, AgentMessageChunk, AgentOutput
│   ├── register.py          # agent 注册（导入触发注册）
│   ├── top_agent.py         # TopAgent — 主路由 Agent（LangGraph DAG）
│   ├── search_agent.py      # SearchAgent — 搜索工作流
│   ├── critic_agent.py      # CriticAgent — VLM 验证搜索结果
│   ├── report_agent.py      # ReportAgent — 单事件报告
│   ├── multi_report_agent.py # MultiReportAgent — 多事件报告
│   └── postprocessing/      # 后处理管道
│       ├── __init__.py
│       ├── data_models.py
│       ├── postprocessing_node.py
│       └── validators/
│           ├── base.py
│           ├── llm_based_rule_validator.py
│           ├── non_empty_response_validator.py
│           └── url_validator.py
├── tools/                   # 工具层
│   ├── __init__.py
│   ├── register.py          # 工具注册
│   ├── search.py            # 核心搜索（数据模型 + 查询分解 + 融合算法 + 核心执行）
│   ├── embed_search.py      # ES 向量搜索
│   ├── attribute_search.py  # ES 属性搜索（行为嵌入 + 帧查找）
│   ├── video_understanding.py # VLM 视频理解
│   ├── video_caption.py     # 视频字幕
│   ├── video_detailed_caption.py
│   ├── video_skim_caption.py
│   ├── video_frame_timestamp.py
│   ├── lvs_video_understanding.py  # 长视频理解
│   ├── vss_summarize.py     # VSS 汇总
│   ├── prompt_gen.py        # VLM prompt 生成
│   ├── report_gen.py        # 报告生成
│   ├── template_report_gen.py
│   ├── video_report_gen.py
│   ├── chart_generator.py
│   ├── fov_counts_with_chart.py
│   ├── incidents.py
│   ├── geolocation.py
│   ├── multi_incident_formatter.py
│   ├── echo_tool.py
│   ├── query_builders.py
│   ├── evaluation_compressor.py
│   ├── s3_picture_url.py
│   ├── rtvi_vlm_alert.py
│   └── vst/                 # VST 服务集成
│       ├── __init__.py
│       ├── duration.py
│       ├── register.py
│       ├── sensor_list.py
│       ├── snapshot.py
│       ├── timeline.py
│       ├── utils.py
│       ├── video_clip.py
│       └── video_list.py
├── embed/                   # 嵌入层
│   ├── __init__.py
│   ├── embed.py             # EmbedClient ABC
│   ├── cosmos_embed.py      # CosmosEmbedClient
│   └── rtvi_cv_embed.py     # RTVICVEmbedClient
├── video_analytics/         # 视频分析层
│   ├── __init__.py
│   ├── es_client.py         # ES 客户端
│   ├── interface.py         # VideoAnalyticsInterface ABC
│   ├── nvschema.py          # Incident/Location/Place 数据模型
│   ├── query_builders.py    # ES 查询构建器
│   ├── tools.py             # 视频分析工具
│   ├── utils.py             # 工具函数
│   └── embeddings.py        # 嵌入操作
├── data_models/             # 共享数据模型
│   ├── __init__.py          # ParserMixin
│   └── vss.py               # MediaInfoOffset/Incident
├── api/                     # API 层
│   ├── __init__.py
│   ├── custom_fastapi_worker.py
│   ├── health_endpoint.py
│   ├── register.py
│   ├── rtsp_stream_api.py
│   ├── video_delete.py
│   ├── video_search_ingest.py
│   └── video_upload_url.py
├── evaluators/              # 评估框架
│   ├── __init__.py
│   ├── evaluate_patch.py
│   ├── register.py
│   ├── utils.py
│   ├── customized_qa_evaluator/
│   ├── customized_trajectory_evaluator/
│   └── report_evaluator/
└── utils/                   # 工具函数
    ├── __init__.py
    ├── asyncmixin.py
    ├── file_mapping.py
    ├── frame_select.py
    ├── markdown_parser.py
    ├── parser.py
    ├── reasoning_parsing.py
    ├── reasoning_utils.py
    ├── retry.py
    ├── time_convert.py
    ├── time_measure.py
    ├── url_translation.py
    └── video_file.py
```

## 二、模块详细分析

### 2.1 agents/data_models.py — Agent 核心数据模型

**文件**: `_nvidia-original/agent/src/vss_agents/agents/data_models.py`

**数据结构**:

| 类/枚举 | 字段 | 说明 |
|---------|------|------|
| `AgentDecision(StrEnum)` | `TOOL`, `END`, `AGENT`, `SUPERVISOR` | Agent 图的条件边决策 |
| `AgentMessageChunkType(StrEnum)` | `THOUGHT`, `TOOL_CALL`, `SUBAGENT_CALL`, `ERROR`, `FINAL` | 流式输出块类型 |
| `AgentMessageChunk` | `type`, `content` | 流式块模型 |
| `AgentOutput` | `messages`, `side_effects`, `metadata`, `status`, `error_message` | 标准化 Agent 输出 |

**函数签名**:
- 无函数，纯数据模型定义

**输入/输出**:
- AgentOutput: 输入无；输出包含 messages(list[str]), side_effects(dict), metadata(dict), status(str), error_message(str|None)

### 2.2 agents/top_agent.py — 主路由 Agent

**文件**: `_nvidia-original/agent/src/vss_agents/agents/top_agent.py` (~1500 行)

**数据结构**:

| 类 | 字段 | 说明 |
|----|------|------|
| `TopAgentRequest(ChatRequestOrMessage)` | `llm_reasoning`, `vlm_reasoning`, `search_source_type` | 扩展的请求模型 |
| `TopAgentState(BaseModel)` | `current_message`, `agent_scratchpad`, `conversation_history`, `iteration_count`, `final_answer`, `plan`, `previous_conversation`, `llm_reasoning`, `vlm_reasoning`, `search_source_type` | LangGraph 状态 |
| `TopAgentConfig(FunctionBaseConfig)` | `tool_names`, `subagent_names`, `llm_name`, `log_level`, `max_iterations`, `max_history`, `prompt`, `llm_reasoning`, `planning_enabled`, `plan_prompt`, `tool_call_prompt`, `response_format_prompt`, `postprocessing` | Agent 配置 |

**函数签名**:

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `TopAgent.__ainit__()` | llm, prompt, tools, subagents, subagent_functions, callbacks, max_iterations, max_history, postprocessing_config, postprocessing_llm, planning_enabled, plan_prompt, plan_exec_prompt, plan_system_prompt, tool_call_prompt, response_format_prompt | None | 异步初始化，构建 LangGraph |
| `TopAgent.astream()` | input_messages, llm_reasoning, vlm_reasoning, search_source_type | AsyncGenerator[AgentMessageChunk] | 流式执行入口 |
| `TopAgent.agent_node()` | state | state | LLM 调用节点 |
| `TopAgent.tool_or_subagent_node()` | state | state | 工具/子 Agent 执行节点 |
| `TopAgent.finalize_node()` | state | state | 最终输出节点 |
| `TopAgent._plan_node()` | state | state | 计划生成节点 |
| `TopAgent._plan_update_node()` | state | state | 计划更新节点 |
| `top_agent()` | config, builder | AsyncGenerator[FunctionInfo] | NAT 注册工厂函数 |

**关键逻辑**:
1. 使用 LangGraph StateGraph 构建 Agent DAG
2. 支持 plan-then-execute 模式（planning_enabled）
3. 支持子 Agent 原生流式（subagent_names）
4. 后处理管道（postprocessing）
5. 对话历史管理（max_history）
6. 使用 `@register_function` 装饰器注册为 NAT 函数

**NAT 依赖**: `nat.builder.*`, `nat.data_models.*`, `nat.cli.register_workflow`, `nat.utils.type_converter`


### 2.11 embed/ — 嵌入层

**文件**: `_nvidia-original/agent/src/vss_agents/embed/`

**数据结构**:

| 类 | 方法 | 说明 |
|----|------|------|
| `EmbedClient(ABC)` | `get_text_embedding()`, `get_image_embedding()`, `get_video_embedding()` | 嵌入客户端抽象基类 |
| `CosmosEmbedClient(EmbedClient)` | 实现三个方法 | NVIDIA Cosmos 嵌入服务 |
| `RTVICVEmbedClient(EmbedClient)` | 实现 `get_text_embedding()` | RTVI CV 文本嵌入 |

**关键逻辑**:
- CosmosEmbedClient: 调用 NVIDIA Cosmos API 生成多模态嵌入
- RTVICVEmbedClient: 调用 RTVI CV API 生成文本嵌入（用于属性搜索）

### 2.12 video_analytics/ — 视频分析层

**文件**: `_nvidia-original/agent/src/vss_agents/video_analytics/`

| 模块 | 说明 |
|------|------|
| `nvschema.py` | Incident/Location/Place 数据模型 |
| `interface.py` | VideoAnalyticsInterface ABC |
| `query_builders.py` | ES 查询构建器 |
| `es_client.py` | ES 客户端封装 |
| `tools.py` | 视频分析工具函数 |
| `utils.py` | 时间桶、事件重叠分析 |
| `embeddings.py` | 嵌入操作 |

### 2.13 utils/ — 工具函数

| 模块 | 函数 | 说明 |
|------|------|------|
| `asyncmixin.py` | AsyncMixin | 异步初始化基类 |
| `frame_select.py` | frame_select() | 从视频中提取帧 |
| `time_convert.py` | iso8601_to_datetime(), datetime_to_iso8601() | 时间格式转换 |
| `time_measure.py` | 计时工具 | 执行时间测量 |
| `url_translation.py` | translate_url() | URL 内外网翻译 |
| `reasoning_parsing.py` | parse_reasoning_content(), parse_content_blocks() | 解析 VLM 推理内容 |
| `reasoning_utils.py` | get_thinking_tag(), get_llm_reasoning_bind_kwargs() | 推理工具函数 |
| `markdown_parser.py` | Markdown 解析 | 解析 markdown 输出 |
| `parser.py` | 通用解析 | 通用解析工具 |
| `video_file.py` | 视频文件工具 | 视频文件操作 |
| `retry.py` | create_retry_strategy() | 重试策略 |
| `file_mapping.py` | 文件映射 | 文件路径映射 |

### 2.14 api/ — API 层

| 模块 | 端点 | 说明 |
|------|------|------|
| `health_endpoint.py` | /health | 健康检查 |
| `video_search_ingest.py` | /ingest | 视频搜索数据摄入 |
| `video_upload_url.py` | /upload-url | 视频上传 URL 生成 |
| `rtsp_stream_api.py` | /rtsp | RTSP 流管理 |
| `video_delete.py` | /delete | 视频删除 |
| `custom_fastapi_worker.py` | 自定义 worker | FastAPI worker 自定义 |

### 2.15 evaluators/ — 评估框架

| 模块 | 说明 |
|------|------|
| `customized_qa_evaluator/` | QA 评估器 |
| `customized_trajectory_evaluator/` | 轨迹评估器 |
| `report_evaluator/` | 报告评估器（含 field_evaluators） |

## 三、数据流分析

### 3.1 搜索数据流

```
User Query
    |
    v
search_agent (agents/search_agent.py)
    |
    +-> decompose_query() (tools/search.py) -- LLM 查询分解
    |       |
    |       v
    |   DecomposedQuery {query, attributes, has_action, ...}
    |
    +-> execute_core_search() (tools/search.py)
            |
            +-> Path 1 (has_action=False + attributes):
            |       attribute_search_fn() -> attribute_results -> SearchOutput
            |
            +-> Path 2 (no attributes):
            |       embed_search_fn() -> embed_results -> SearchOutput
            |
            +-> Path 3 (has_action=True + attributes):
                    embed_search_fn() -> embed_results
                    attribute_search_fn() -> attribute_results
                    fusion_search_rerank() -> reranked_results
                    critic_agent (optional) -> verified_results
                    -> SearchOutput
```

### 3.2 视频理解数据流

```
video_understanding (tools/video_understanding.py)
    |
    +-> Get video URL (VST or MinIO)
    +-> Calculate num_frames = min(duration * max_fps, max_frames)
    +-> Build VLM messages (video URL or base64 frames)
    +-> Call VLM with retry
    +-> Parse thinking/answer
    +-> Return caption string
```

### 3.3 TopAgent 数据流

```
TopAgent.astream()
    |
    +-> agent_node: LLM call -> tool_calls or final_answer
    +-> tool_or_subagent_node: execute tools/sub-agents
    +-> (optional) plan_node -> plan_update_node -> agent_node
    +-> (optional) postprocessing_node
    +-> finalize_node: emit FINAL chunk
```
