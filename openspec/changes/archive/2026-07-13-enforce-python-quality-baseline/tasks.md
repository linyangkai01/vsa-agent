## 1. 配置与基线

- [x] 1.1 在 `stabilize-test-contracts` 完成后重新记录 `src/` 和 `tests/` 的 Ruff JSON、格式及全量测试基线。
- [x] 1.2 将 Ruff lint 选择迁移到当前配置结构，保持现有规则集合和 120 列限制。

## 2. 安全机械整理

- [x] 2.1 应用 Ruff 安全修复，处理导入顺序、类型现代化和可确定的语法问题。
- [x] 2.2 对 `src/` 和 `tests/` 运行 Ruff 格式化，并将纯格式差异与语义修复分开审查。
- [x] 2.3 人工处理剩余长行、未使用变量和未使用导入，保持 prompt 与稳定字符串内容不变。

## 3. 注册与兼容验证

- [x] 3.1 审查 agents/tools 注册入口中的导入副作用，用显式别名、`__all__` 或窄范围说明表达用途。
- [x] 3.2 运行注册表、配置、prompt 和受影响模块的针对性测试，确认机械整理不改变行为。

## 4. 完整质量门禁

- [x] 4.1 运行 `ruff check src tests` 并达到零问题。
- [x] 4.2 运行 `ruff format --check src tests` 并达到零格式差异。
- [x] 4.3 运行全量 `pytest -q`，并更新 `docs/DEVELOPMENT_STATUS.md` 的质量基线与命令。

<!-- review skipped: multi-agent execution was not authorized for this run -->
