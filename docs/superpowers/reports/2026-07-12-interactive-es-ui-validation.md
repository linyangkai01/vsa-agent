# 原版 UI ES 交互验收报告

日期：2026-07-12

## 结论

通过。Ubuntu 服务器上的原版 VSS Search UI 已经完成从浏览器输入到
Elasticsearch 返回结果的验证。验证运行时使用临时配置中的确定性 mock
embedding，仅证明开发验证链路，不代表生产语义检索质量。

## 运行环境

- 服务器项目：`/data/project/lyk/vsa-agent`
- 启动命令：

  ```bash
  ./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
  ```

- 浏览器访问：SSH UI 隧道 `ssh -L 3000:127.0.0.1:3000 10.157.68.44`
- 浏览器查询：`forklift near worker`

## 浏览器证据

原版 Search 页面返回一条 `runtime-validation.mp4`，时间范围为
`08:00:00/08:00:05`，相似度为 `1.00`。稳定 smoke ID 和受限的历史
验证数据清理生效，页面不再展示此前重复的验证样本。

## API 证据

`/data/project/lyk/vsa-agent/.runtime/es-stack/api.log` 记录了两次 ES
搜索路径：

```text
INFO vsa_agent.api.original_ui_search original_ui.search.request query='forklift near worker' top_k=1 agent_mode=False
INFO vsa_agent.agents.search_agent search_agent.embed_search path=embed-only query='forklift near worker'
INFO:     127.0.0.1:43180 - "POST /api/v1/search HTTP/1.1" 200 OK

INFO vsa_agent.api.original_ui_search original_ui.search.request query='forklift near worker' top_k=10 agent_mode=False
INFO vsa_agent.agents.search_agent search_agent.embed_search path=embed-only query='forklift near worker'
INFO:     127.0.0.1:39184 - "POST /api/v1/search HTTP/1.1" 200 OK
```

`top_k=1` 来自启动器 smoke 验证，`top_k=10` 来自浏览器 Search 操作。

## UI 日志证据

UI 已输出 `Ready in 2.8s`。扫描本次 `ui.log` 和 `ui.err.log` 未发现
`failed to read input source map`、`Module not found` 或 `EADDRINUSE`。

## 本地回归

```text
69 passed, 1 warning
Change 'script-es-runtime-stack' is valid
```

PowerShell 与 Bash 启动器语法检查均通过；相关文件已同步到 `Z:\vsa-agent`
并完成 SHA-256 一致性核对。
