## Why

`scripts/` 中的 14 个入口都能找到文档、测试、包命令或其他脚本引用，因此不能按文件名直接删除；但两个 DashScope 验收入口重复了配置、密钥和 Conda 前置逻辑，运行栈和同步脚本也需要更清晰的职责边界。本 change 以当前工作树为审计基线，并冻结仍由生产录制视频 change 演进的 ES 运行栈文件。

## What Changes

- 建立 `scripts/` 入口、调用者、平台和验证方式清单。
- 抽取两个 DashScope 验收脚本的共享前置逻辑，同时保留各自的测试和视频验收语义。
- 明确 ES、API、UI 启动、smoke、同步和依赖安装脚本的职责边界。
- 仅在完成引用迁移、文档更新和回归验证后删除真正无引用的脚本。
- 保留必要的 Windows/Linux 双平台入口，不把跨平台实现误判为冗余。

## Capabilities

### New Capabilities

- `runtime-script-consolidation`: 为本地、测试和服务器验证脚本提供可追踪且低重复的入口组织。

### Modified Capabilities

无。此 change 不改变脚本对外参数和运行结果要求。

## Impact

- 影响 `scripts/`、脚本单元测试、`package.json` 和运行文档。
- 不修改 `production-recorded-video-ingest` 仍会演进的 `es-runtime-stack.*` 生命周期；允许修复同步清单中的陈旧文件引用。
- 不检查或重构 `frontend/original-ui` 内部源码。
