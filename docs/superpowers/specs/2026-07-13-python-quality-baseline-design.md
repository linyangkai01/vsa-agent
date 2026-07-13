---
comet_change: enforce-python-quality-baseline
role: technical-design
canonical_spec: openspec
---

# Python 质量基线技术设计

## 基线与边界

质量治理覆盖 `src/` 与 `tests/`，排除 `frontend/original-ui`。现有 Ruff 规则为 `E/F/I/N/W/UP`，行宽 120；本 change 只迁移配置位置并清理存量，不扩大规则集合或引入新工具。

## 分层修复

第一层迁移 `[tool.ruff] select` 到 `[tool.ruff.lint] select`，保留规则和行宽。第二层执行 Ruff 安全修复，处理导入排序、标准库导入位置、类型现代化等可机械证明的修改。第三层执行 Ruff formatter。第四层人工处理剩余 `F401`、`F841` 与 `E501`。

注册入口中的导入可能依赖模块加载副作用。对这类文件先运行注册测试，再用显式重导出、冗余别名或窄范围 `noqa: F401` 表达意图；只有确认没有调用者或副作用的导入才能删除。长 prompt、错误信息和其他稳定字符串使用括号拼接或局部格式调整，运行时内容必须保持一致。

## 替代方案

不使用 `ruff check --unsafe-fixes`，因为它可能改变注解、导入和兼容行为。不建立大范围 ignore baseline，因为那会把现有债务永久固化。不把架构拆分混入格式化提交，视频理解与搜索拆分由后续独立 change 处理。

## 验证顺序

1. 记录 lint JSON、format check 和 pytest 基线。
2. 迁移配置并运行 Ruff 安全修复。
3. 格式化后执行 compileall 和受影响的注册/config/prompt 测试。
4. 人工处理剩余问题，每类修复后重复相关测试。
5. 最终执行 `ruff check src tests`、`ruff format --check src tests` 和全量 `pytest -q`。

## 回滚策略

配置迁移、安全修复、格式化和人工语义修复分开提交。若测试失败，先回滚对应类别提交，不关闭 Ruff 规则或降低测试断言。
