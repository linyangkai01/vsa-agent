# 项目学习进度

> 文档驱动的学习同步方案 — 开发对话 ↔ 学习对话

## 工作流

1. **开发对话** 实现新模块后，在下方标记为 🆕 新增待学习
2. **开发对话** 通知学习对话"请同步"
3. **学习对话** 扫描 🆕 或 🔄 模块，生成/更新学习文档
4. **学习对话** 将状态改为 ✅ 已学习，更新 INDEX.md

---

## 源码模块清单

### L01: Config + Registry — 系统基石

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/config.py` | ✅ 已学习 | L01 | 2026-06-10 |
| `src/vsa_agent/registry.py` | ✅ 已学习 | L01 | 2026-06-10 |

### L02: Data Models — 核心数据结构

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/agents/data_models.py` | ✅ 已学习 | L02 | 2026-06-10 |
| `src/vsa_agent/data_models/vss.py` | ✅ 已学习 | L02 | 2026-06-10 |
| `src/vsa_agent/video_analytics/nvschema.py` | ✅ 已学习 | L02 | 2026-06-10 |

### L03: Model Adapter — LLM/VLM 抽象层

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/model_adapter/base.py` | ✅ 已学习 | L03 | 2026-06-10 |
| `src/vsa_agent/model_adapter/openai_adapter.py` | ✅ 已学习 | L03 | 2026-06-10 |
| `src/vsa_agent/model_adapter/vllm_adapter.py` | ✅ 已学习 | L03 | 2026-06-10 |
| `src/vsa_agent/model_adapter/__init__.py` | ✅ 已学习 | L03 | 2026-06-10 |

### L04: Search — 核心搜索（三路径路由）

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/tools/search.py` | ✅ 已学习 | L04 | 2026-06-10 |
| `src/vsa_agent/tools/embed_search.py` | ✅ 已学习 | L04 | 2026-06-10 |
| `src/vsa_agent/tools/attribute_search.py` | ✅ 已学习 | L04 | 2026-06-10 |

### L05: Video Understanding — VLM 视频分析

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/tools/video_understanding.py` | ✅ 已学习 | L05 | 2026-06-10 |
| `src/vsa_agent/tools/frame_extract.py` | ✅ 已学习 | L05 | 2026-06-10 |
| `src/vsa_agent/tools/frame_store.py` | ✅ 已学习 | L05 | 2026-06-10 |

### L06: Agents — 业务流程编排

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/agents/top_agent.py` | ✅ 已学习 | L06 | 2026-06-10 |
| `src/vsa_agent/agents/search_agent.py` | ✅ 已学习 | L06 | 2026-06-10 |
| `src/vsa_agent/agents/critic_agent.py` | ✅ 已学习 | L06 | 2026-06-10 |

### L07: Video Analytics — 事件分析层

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/video_analytics/interface.py` | ✅ 已学习 | L07 | 2026-06-10 |
| `src/vsa_agent/video_analytics/query_builders.py` | ✅ 已学习 | L07 | 2026-06-10 |
| `src/vsa_agent/video_analytics/tools.py` | ✅ 已学习 | L07 | 2026-06-10 |
| `src/vsa_agent/video_analytics/utils.py` | ✅ 已学习 | L07 | 2026-06-10 |

### L08: Postprocessing — 输出验证

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/agents/postprocessing/pipeline.py` | ✅ 已学习 | L08 | 2026-06-10 |
| `src/vsa_agent/agents/postprocessing/validators/base.py` | ✅ 已学习 | L08 | 2026-06-10 |
| `src/vsa_agent/agents/postprocessing/validators/non_empty.py` | ✅ 已学习 | L08 | 2026-06-10 |
| `src/vsa_agent/agents/postprocessing/validators/safety_checklist.py` | ✅ 已学习 | L08 | 2026-06-10 |
| `src/vsa_agent/agents/postprocessing/validators/url_check.py` | ✅ 已学习 | L08 | 2026-06-10 |

### L09: API + Embed — 外围层

| 模块路径 | 状态 | 学习文档 | 最后更新 |
|---------|------|---------|---------|
| `src/vsa_agent/api/routes.py` | ✅ 已学习 | L09 | 2026-06-10 |
| `src/vsa_agent/api/health.py` | ✅ 已学习 | L09 | 2026-06-10 |
| `src/vsa_agent/embed/embed.py` | ✅ 已学习 | L09 | 2026-06-10 |
| `src/vsa_agent/embed/cosmos_embed.py` | ✅ 已学习 | L09 | 2026-06-10 |

---

## 未覆盖模块（暂无学习文档）

以下模块存在于源码中，但尚未纳入任何学习课程：

| 模块路径 | 建议归属 | 说明 |
|---------|---------|------|
| `src/vsa_agent/main.py` | 启动入口 | Uvicorn 启动脚本，含生命周期事件 |
| `src/vsa_agent/prompt.py` | 辅助 | 提示词加载（部分已移入 config.yaml） |
| `src/vsa_agent/agents/register.py` | L06 | Agent 注册辅助函数 |
| `src/vsa_agent/api/video_search_ingest.py` | L09 | 视频搜索索引端点 |
| `src/vsa_agent/api/video_upload_url.py` | L09 | 视频上传预签名 URL 端点 |
| `src/vsa_agent/tools/find_video_tool.py` | 工具 | 按名称查找视频文件 |
| `src/vsa_agent/tools/query_builders.py` | L04 | 搜索查询构建器（与 video_analytics/query_builders.py 不同） |
| `src/vsa_agent/tools/register.py` | L04 | 工具注册辅助函数 |
| `src/vsa_agent/tools/vector_store.py` | L04 | 向量存储实现 |
| `src/vsa_agent/tools/video_db.py` | L04 | 视频数据库接口 |
| `src/vsa_agent/utils/asyncmixin.py` | 工具 | 异步混入类 |
| `src/vsa_agent/utils/frame_select.py` | L05 | 帧选择策略 |
| `src/vsa_agent/utils/reasoning_parsing.py` | L05 | VLM 推理内容解析 |
| `src/vsa_agent/utils/reasoning_utils.py` | L05 | 推理工具函数 |
| `src/vsa_agent/utils/retry.py` | 工具 | 重试机制 |
| `src/vsa_agent/utils/time_convert.py` | 工具 | 时间格式转换 |
| `src/vsa_agent/utils/url_translation.py` | 工具 | URL 翻译/转换 |
| `src/vsa_agent/mcp/server.py` | 外围 | MCP 服务器（独立协议） |

---

## 状态标记说明

| 标记 | 含义 | 行动 |
|------|------|------|
| ✅ 已学习 | 已有学习文档，源码无变更 | 无需操作 |
| 🆕 新增待学习 | 刚实现的新模块，等待生成文档 | 学习对话需生成新文档 |
| 🔄 代码已变更 | 已有文档但源码有更新 | 学习对话需更新文档 |

