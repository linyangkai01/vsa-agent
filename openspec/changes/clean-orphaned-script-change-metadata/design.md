## Context

`script-es-runtime-stack` 的完整 OpenSpec 产物已位于归档目录，但旧活动目录只剩 `.comet` 恢复快照。快照指向已不存在的文件，导致 OpenSpec 把历史 change 显示为活动项。

## Goals / Non-Goals

**Goals:**
- 让 active change 列表只包含可恢复的 change。
- 保留归档的 proposal、design、tasks、spec 和验证证据。
- 以最小删除和可重复的只读验证完成清理。

**Non-Goals:**
- 不删除或重构任何 `scripts/` 文件。
- 不修改已归档 change 的内容、历史提交或运行时规范。
- 不改变 OpenSpec 或 Comet 工具实现。

## Decisions

- 删除整个孤立活动目录，而不是修复其中的快照。目录没有 `.openspec.yaml` 外的可恢复 artifacts，快照的源文件均已迁移到归档目录；保留它只会制造错误的活动状态。
- 把归档目录作为唯一历史来源。它已被同步 manifest、验证报告和运行文档引用，避免引入第二份历史副本。
- 使用 `openspec list --json`、归档目录存在性和脚本清单引用检查验证。它们直接覆盖本次 metadata 状态，不需要启动 Elasticsearch、API 或 UI。

## Risks / Trade-offs

- [误删未归档文件] → 删除前验证孤立目录只含 `.comet`，且归档目录包含完整 artifacts。
- [隐藏运行脚本依赖] → 搜索 `scripts/`、文档、测试和同步 manifest；本 change 不删除任何脚本。
- [工具缓存残留] → 以新的 `openspec list --json` 输出作为完成判据。
