## Context

仓库当前跟踪 14 个运行脚本。引用审计显示每个脚本至少被文档、测试、`package.json` 或另一个脚本使用，因此没有可直接删除的死入口。`run_live_acceptance_dashscope.sh` 与 `run_live_top_agent_video_dashscope.sh` 重复了仓库定位、Conda 检查、配置检查、API key 检查和 runtime config 解析；ES 的 PowerShell/Bash 入口则承担不同平台的必要职责。

## Goals / Non-Goals

**Goals:**

- 让每个脚本入口有明确调用者、平台、职责和验证方式。
- 集中 DashScope 运行前置逻辑，保留现有用户入口。
- 删除经过引用迁移后确实无用的脚本或重复包装层。

**Non-Goals:**

- 不检查或修改 `frontend/original-ui` 内部代码。
- 不合并 Windows 与 Linux 必需的运行栈入口。
- 不重写 `production-recorded-video-ingest` 正在修改的运行栈。

## Decisions

1. 先建立机器可审查的脚本清单，记录入口、调用者、平台、依赖和验证命令。没有调用证据迁移的脚本不得删除。
2. 新增单一的 shell 公共 helper，封装仓库定位、Conda/config/key 校验和 runtime config 解析；两个 DashScope 用户入口保留为薄包装，分别启动 evaluator live API 与 TopAgent 视频验收。
3. `es-runtime-stack.ps1` 与 `es-runtime-stack.sh` 继续作为平台入口，生命周期子脚本继续由运行栈组合。共享语义通过测试对齐，不强制跨语言源码复用。
4. `install_original_ui_deps.sh`、`run_original_ui_vss.sh`、`run_original_ui_debug_stack.sh` 和 smoke 入口保持职责独立；只有当新入口完整替代调用者时才考虑删除。
5. 与生产录制视频 change 重叠的文件只纳入清单，不修改其实现；DashScope wrapper 与其无文件重叠，可独立治理。

## Risks / Trade-offs

- [风险] source 公共 helper 可能改变环境变量作用域。 -> helper 只导出明确约定变量，并用 wrapper 测试验证。
- [风险] 删除脚本会留下文档或包命令悬空。 -> 删除前后执行全仓文件名引用扫描并更新调用者。
- [风险] 跨平台入口继续存在源码重复。 -> 保留必要平台实现，以共享验收场景约束语义一致。

## Migration Plan

1. 以当前工作树生成引用清单，并冻结生产录制视频运行栈的重叠文件。
2. 引入公共 helper，逐个迁移 DashScope wrapper 并保持原命令可用。
3. 更新测试、包命令和文档；仅删除引用数归零且功能已迁移的入口。
4. 任一入口回归时恢复原 wrapper，公共 helper 可独立回滚。

## Open Questions

无。
