## 为什么需要这项变更

项目已有 Elasticsearch 写入、检索测试以及独立的 ES 启停脚本，但完整验证仍需要手工执行多步命令。本变更将验证流程收敛为一条可重复的运行链路：启动 ES，使用临时搜索配置启动 FastAPI，执行 ingest/search smoke，并在结束时清理由脚本拥有的服务。

## 变更内容

- 增加可脚本化的 ES、FastAPI 和原版 UI 运行栈入口，支持本地与映射服务器验证。
- 生成只用于本次验证的搜索配置，不修改提交版本的默认 `config.yaml`。
- 为 ES、FastAPI 和 ingest/search smoke 增加健康检查以及明确的 PASS/FAIL 输出。
- 增加清理逻辑，避免验证服务在退出后残留；首次使用尚未创建索引时跳过历史记录清理。
- 交互模式等待原版 UI HTTP 就绪，UI 启动失败或异常退出时不得报告验证成功。
- 更新文档，使 `Z:\vsa-agent` 可以执行相同的验证命令。

## 能力范围

### 新增能力

无。

### 修改能力

- `recorded-video-business-flow`：将 Elasticsearch 运行时验证从“存在 ingest/search smoke 路径”扩展为“提供可脚本化的 ES、API、原版 UI 启动、smoke 验证和清理流程”。

## 影响范围

- 脚本：ES 生命周期脚本以及新的栈级验证入口。
- API 运行时：通过 Uvicorn 启动 `vsa_agent.api.routes:app`。
- 临时配置：`VSA_CONFIG` 覆盖 `search.enabled`、`search.es_endpoint`、`search.embed_index` 和 `search.verify_certs`。
- 文档：ES 运行时指南和服务器映射盘验证说明。
- 测试：覆盖配置生成、命令拼接、端口/健康检查、缺失索引和 UI 就绪失败路径的聚焦测试。
