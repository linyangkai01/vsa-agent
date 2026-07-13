## 1. 验证孤立 change 状态

- [x] 1.1 确认活动 `script-es-runtime-stack` 目录只含失效 Comet 元数据，且完整历史 change 位于 `openspec/changes/archive/2026-07-12-script-es-runtime-stack/`。

## 2. 删除失效元数据并验证引用

- [x] 2.1 删除孤立活动 change 目录，再验证 `openspec list --json`、运行脚本清单和 `sync-server-files.ps1` 仅保留归档引用。
