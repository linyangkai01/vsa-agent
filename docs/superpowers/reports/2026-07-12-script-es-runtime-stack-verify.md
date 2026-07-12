# ES 运行栈变更验证报告

日期：2026-07-12

## 结论

`script-es-runtime-stack` 的实现、规格和测试证据一致，可以进入归档。分支已合并到本地 `master`，并已推送远程 `master`。

## 完整性

- OpenSpec 任务：24/24 完成。
- 实现覆盖临时搜索配置、ES/API/UI 启动、smoke 写入与检索、原版 UI 搜索代理、端口接管、日志输出和定向服务器同步。
- 本次审查补充的两个边界已覆盖：新 ES 卷没有索引时跳过历史记录删除；Windows UI 必须 HTTP 就绪后才能报告成功。

## 正确性

- `python -m pytest`：704 passed，4 skipped，1 warning。
- Bash 语法检查通过。
- PowerShell 启动器语法检查通过。
- `openspec validate script-es-runtime-stack --strict` 通过。
- Ubuntu 交互验收已记录于 `docs/superpowers/reports/2026-07-12-interactive-es-ui-validation.md`：原版 UI 查询返回一个 `runtime-validation.mp4`，API 日志同时包含 `original_ui.search.request` 与 `search_agent.embed_search`。
- Windows UI 就绪、提前退出、非零退出和日志路径由 `tests/unit/scripts/test_es_runtime_stack_script.py` 的静态回归契约覆盖；本次未在 Windows 上执行 Docker/浏览器实测。

## 一致性

- `recorded-video-business-flow` 的 runtime 场景与实现一致：`/api/search/ingest` 使用 `video_id` 覆盖写入，原版 UI 通过同源 `/api/v1/search` 代理进入 SearchAgent 和 `embed_search`。
- 临时配置启用确定性 mock embedding，仅用于验证，不改变提交配置的默认搜索开关。
- 映射服务器目标 `Z:\vsa-agent` 已完成定向同步；关键修复文件的 SHA-256 与本地源文件一致。

## 已知限制

- 验收环境使用确定性 mock embedding，证明的是业务链路与 ES 调用，不代表生产语义检索质量。
