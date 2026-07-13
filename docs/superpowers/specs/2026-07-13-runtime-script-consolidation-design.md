---
comet_change: consolidate-runtime-scripts
role: technical-design
canonical_spec: openspec
---

# 运行脚本整理技术设计

## 范围与审计结论

治理范围是仓库根目录 `scripts/` 和直接验证这些入口的 Python 测试、包命令及运行文档。`frontend/original-ui` 内部源码不在范围内。当前 14 个脚本都有文档、测试、包命令或脚本间调用证据，因此本 change 不删除用户入口；新增的共享文件是被 source 的实现 helper，不计为用户入口。

`es-runtime-stack.sh`、`es-runtime-stack.ps1`、Elasticsearch 生命周期脚本、UI 启动脚本、smoke、依赖安装和服务器同步入口职责不同。它们在清单中标记为保留，本 change 不修改仍由 `production-recorded-video-ingest` 演进的运行栈实现。

## 组件边界

新增 `scripts/lib/dashscope_runtime.sh`，只提供 DashScope 验收公共前置函数。函数负责：

1. 从 helper 位置稳定解析仓库根目录和 `config.yaml`。
2. 在运行任何配置解析命令前检查 Conda、配置文件和 `DASHSCOPE_API_KEY`。
3. 设置 `DASHSCOPE_BASE_URL`、`VSA_CONDA_ENV`、`VSA_PROFILE` 和 `VSA_CONFIG` 默认值。
4. 执行现有 `config doctor` 与 `config print`。
5. 解析并导出带 `VSA_RESOLVED_LLM_` 前缀的 key、base URL 和 model；解析结果为空时失败退出。

`run_live_acceptance_dashscope.sh` source helper 后设置 trace 默认值，调用公共前置函数，再将解析结果映射到现有 `LIVE_API_*` 环境变量并运行 evaluator live API 测试。

`run_live_top_agent_video_dashscope.sh` source helper 后保留 `VSA_LIVE_VIDEO_MODE`、位置参数、配置默认视频路径和 query 分支，将公共 key 映射到现有 `OPENAI_API_KEY`，最后运行 `vsa_agent.live_video_acceptance`。

## 接口与错误处理

两个用户命令、位置参数、默认 profile、默认 Conda 环境、错误码 `2` 和现有错误文本保持不变。helper 不使用 `eval`，不读取或写入 `.env`，不打印密钥。所有导出变量显式命名，wrapper 继续负责目标流程专用变量。

脚本清单写入 `docs/superpowers/reference/runtime-scripts.md`，每行记录脚本、平台、职责、调用证据、验证命令和处理结论。删除规则是先迁移所有调用者，再用全仓引用扫描证明归零；本轮没有满足条件的删除候选。

## 测试策略

- Red：测试要求两个 wrapper source 同一 helper，公共校验只在 helper 中出现，原入口命令和参数仍存在。
- Green：实现最小 helper 和薄 wrapper，验证缺少 key 时仍在配置解析前以状态 2 退出。
- 静态：对所有 Bash 文件执行 `bash -n`，对所有 PowerShell 文件使用 ScriptBlock parser。
- 回归：运行 `tests/unit/test_dashscope_live_runner.py`、脚本目录测试和全量 `pytest -q`。
- 运维：运行 `scripts/sync-server-files.ps1 -PreflightOnly`；不在缺少真实凭据时启动 DashScope 或改写服务器运行栈。

## 回滚

回滚时把两个 wrapper 恢复为内联前置逻辑并删除 helper；用户入口、参数和文档链接不变。清单文档可以独立保留，不影响运行时。
