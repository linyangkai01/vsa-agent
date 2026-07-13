## Why

`script-es-runtime-stack` 已归档，但其旧活动目录仍保留失效的 Comet 恢复元数据。它让 OpenSpec 将已完成的 change 显示为无任务的活动项，干扰后续脚本治理和状态恢复。

## What Changes

- 删除 `openspec/changes/script-es-runtime-stack/` 下指向已不存在 proposal、design、tasks 和 delta spec 的残留 `.comet` 元数据。
- 保留 `openspec/changes/archive/2026-07-12-script-es-runtime-stack/` 的归档产物及所有受支持的运行脚本。
- 用只读检查验证 active change 列表、脚本清单和服务器同步 manifest 不再引用该孤立活动目录。

## Capabilities

### New Capabilities

- `workflow-metadata-hygiene`: 已归档 change 的活动恢复元数据清理规则。

### Modified Capabilities

无。此 change 不修改任何运行时或规范行为。

## Impact

仅影响 OpenSpec/Comet 的历史元数据目录。不会修改 `scripts/`、应用代码、测试、依赖、公开 API 或归档的脚本运行栈记录。
