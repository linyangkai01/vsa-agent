## Why

Python 运行时代码与测试目前存在 124 个 Ruff 问题，其中 99 个可自动修复，另有 63 个源码文件格式不一致。存量导入、未使用变量、过时类型写法和长行噪声降低了审查信噪比，也让后续重构更容易引入无关差异。

## What Changes

- 清理 `src/` 和 `tests/` 的现有 Ruff 问题，包括未使用导入/变量、导入顺序、类型写法和明确的长行问题。
- 统一受控 Python 文件的 Ruff 格式。
- 将 Ruff 配置迁移到当前配置结构，并保留项目既定规则和 120 列约束。
- 建立可重复执行的静态质量门禁，避免债务重新累积。

## Capabilities

### New Capabilities

- `python-quality-baseline`: 为 Python 运行时代码和测试提供可执行的静态质量基线。

### Modified Capabilities

无。此 change 不改变生产能力或对外契约。

## Impact

- 影响 `pyproject.toml`、`src/`、`tests/` 及相关开发文档或验证命令。
- 需要在静态检查后运行全量测试，确认机械整理没有改变行为。
- 排除 `frontend/original-ui` 及其 JavaScript/TypeScript 依赖。
