# python-quality-baseline Specification

## Purpose
TBD - created by archiving change enforce-python-quality-baseline. Update Purpose after archive.
## Requirements
### Requirement: Python 静态检查门禁
仓库 SHALL 对 `src/` 和 `tests/` 执行统一 Ruff 检查，并保持零未处理问题。

#### Scenario: 执行静态检查
- **WHEN** 开发者运行 `ruff check src tests`
- **THEN** 命令 MUST 成功退出且不报告 lint 问题

### Requirement: Python 格式门禁
仓库 SHALL 使用 Ruff 作为受控 Python 文件的统一格式标准。

#### Scenario: 执行格式检查
- **WHEN** 开发者运行 `ruff format --check src tests`
- **THEN** 命令 MUST 成功退出且不要求重新格式化文件

### Requirement: 注册副作用保持
静态债务清理 MUST 保留依赖导入副作用建立的工具和代理注册行为。

#### Scenario: 清理未使用导入
- **WHEN** Ruff 报告注册入口中的表面未使用导入
- **THEN** 实现 MUST 显式表达其注册用途并通过注册表测试，而不是无条件删除该导入

### Requirement: 质量整理保持行为
格式化和静态修复 MUST NOT 改变公开 API、数据模型、prompt 内容或运行时结果。

#### Scenario: 完成质量整理
- **WHEN** 所有 Ruff 问题和格式差异被清除
- **THEN** 全量 pytest 套件 MUST 继续通过
