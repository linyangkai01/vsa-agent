---
comet_change: stabilize-test-contracts
role: technical-design
canonical_spec: openspec
---

# 测试收集稳定化技术设计

## 背景

`tests/__init__.py` 与 `tests/unit/__init__.py` 已存在，但 `tests/unit/archive/` 和 `tests/unit/recorded_video/` 没有包边界。pytest 默认 prepend 导入模式把两个 `test_models.py` 都注册为顶层 `test_models`，因此全量收集出现 `import file mismatch`。两个文件单独执行分别通过，证明失败来自模块身份冲突，而非测试断言或生产实现。

## 方案比较

采用局部包边界：为冲突测试目录增加 `__init__.py`，让模块名成为 `tests.unit.archive.test_models` 与 `tests.unit.recorded_video.test_models`。该方案局部、可回滚，并沿用仓库已经存在的父级测试包结构。

不采用全局 `--import-mode=importlib`。该模式也能解决冲突，但会改变整个测试树的导入行为，影响范围明显大于当前问题。不采用重命名测试文件，因为它只修复当前一对文件，不能建立可持续的目录模块身份。

## 实现边界

- 扫描测试树中的重复 Python basename，确认所有冲突目录。
- 只在需要唯一模块身份的测试目录增加空包初始化文件。
- 不修改 `src/`、pytest testpaths、断言或 skip 配置。
- 不把 Ruff 和格式债务混入本 change。

## 验证流程

1. 修复前执行两个目标文件的组合收集，记录可重复失败。
2. 添加包边界后执行两个文件的组合收集与组合测试。
3. 分别执行两个文件，确认测试数量和结果不变。
4. 执行 `pytest --collect-only` 与 `pytest -q` 全量门禁。

## 风险控制

包初始化可能改变测试内部的相对导入解析。如果目标测试或 fixture 出现导入差异，只回滚对应目录的包边界并重新评估，不通过排除目录或降低断言规避失败。
