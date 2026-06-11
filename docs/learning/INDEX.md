# VSA Agent 学习索引

> **项目**：Video Safety Analysis Agent
> **路径**：`C:\working\myproj\vsa-agent`
> **学习目标**：从核心到外围，系统性地理解 VSA Agent 的技术栈和架构设计

---

## 课程列表

| # | 课程 | 模块 | 核心文件 | 状态 |
|---|------|------|----------|------|
| 01 | [Config + Registry — 系统基石](L01-config-registry.md) | 配置加载 + 工具注册 | `config.py`, `registry.py` | ✅ 完成 |
| 02 | [Data Models — 核心数据结构](L02-data-models.md) | Agent 状态 + 事件模型 | `agents/data_models.py`, `data_models/vss.py`, `video_analytics/nvschema.py` | ✅ 完成 |
| 03 | [Model Adapter — LLM/VLM 抽象层](L03-model-adapter.md) | Strategy 模式 | `model_adapter/base.py`, `openai_adapter.py`, `vllm_adapter.py` | ✅ 完成 |
| 04 | [Search — 核心搜索（三路径路由）](L04-search.md) | Three-Path Search Strategy | `tools/search.py`, `embed_search.py`, `attribute_search.py` | ✅ 完成 |
| 05 | [Video Understanding — VLM 视频分析](L05-video-understanding.md) | 帧提取 + VLM 分析 | `tools/video_understanding.py`, `frame_extract.py`, `frame_store.py` | ✅ 完成 |
| 06 | [Agents — 业务流程编排](L06-agents.md) | LangGraph DAG | `agents/top_agent.py`, `search_agent.py`, `critic_agent.py` | ✅ 完成 |
| 07 | [Video Analytics — 事件分析层](L07-video-analytics.md) | ES 查询 + 时间分析 | `video_analytics/interface.py`, `query_builders.py`, `tools.py`, `utils.py` | ✅ 完成 |
| 08 | [Postprocessing — 输出验证](L08-postprocessing.md) | Pipeline 模式 | `agents/postprocessing/pipeline.py`, `validators/` | ✅ 完成 |
| 09 | [API + Embed — 外围层](L09-api-embed.md) | FastAPI + 嵌入 | `api/routes.py`, `embed/embed.py`, `cosmos_embed.py` | ✅ 完成 |

---

## 学习路径图

```
L01: Config + Registry  ─────────────────── 系统基石
        │
L02: Data Models  ───────────────────────── 核心数据结构
        │
L03: Model Adapter  ─────────────────────── LLM/VLM 抽象层
        │
        ├── L04: Search (三路径路由) ─────── 核心搜索
        │       │
        │       └── L05: Video Understanding ─ VLM 视频分析
        │
        ├── L06: Agents (LangGraph DAG) ─── 业务流程编排
        │       │
        │       ├── L07: Video Analytics ─── 事件分析层
        │       │
        │       └── L08: Postprocessing ──── 输出验证
        │
        └── L09: API + Embed ────────────── 外围层
```

---

## 核心设计模式总结

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **Strategy** | Model Adapter | 不同 LLM/VLM 提供商的统一接口 |
| **Three-Path Search** | Search | 根据查询特征自动选择搜索路径 |
| **Pipeline** | Postprocessing | 验证器链式执行 |
| **Self-Check Loop** | Critic Agent | VLM 验证搜索结果 |
| **Registry Table** | Registry | 工具自动发现和注册 |
| **Singleton** | Config | 全局唯一配置实例 |
| **Retry with Exponential Backoff** | utils/retry.py | 异步函数自动重试 |
| **ABC (Abstract Base Class)** | Model Adapter, Embed, Video Analytics | 定义接口契约 |
| **Factory** | Model Adapter | 根据配置创建对应适配器 |

---

## 项目依赖关系

```
api/ --> agents/ --> model_adapter/ + registry/ --> config/
                         ||
                    tools/ (search, video_understanding, ...)
                         ||
                    embed/ + video_analytics/
```

---

## 快速参考

- **运行**：`$env:PYTHONPATH="C:\working\myproj\vsa-agent\src"; & "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m vsa_agent.main`
- **测试**：`$env:PYTHONPATH="C:\working\myproj\vsa-agent\src"; & "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m pytest tests\unit -v`
- **配置**：`config.yaml`（通过 `VSA_CONFIG` 环境变量覆盖路径）
- **开发模型**：DashScope `qwen-plus` / `qwen3-vl-plus`
- **生产模型**：vLLM `Qwen3-VL-8B-Instruct`
