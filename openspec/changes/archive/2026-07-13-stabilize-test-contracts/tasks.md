## 1. 固化收集失败

- [x] 1.1 添加或更新回归检查，同时收集两个同名 `test_models.py` 并确认修复前稳定失败。
- [x] 1.2 扫描 `tests/` 中其他重复 basename，记录缺少包边界且可能发生冲突的目录。

## 2. 建立测试包边界

- [x] 2.1 为冲突目录增加最小 Python 包边界，使同名测试获得唯一完整模块名。
- [x] 2.2 验证新增包边界不改变现有 fixture、导入和单文件测试行为。

## 3. 验证与状态更新

- [x] 3.1 运行两个冲突文件的组合收集和组合测试，确认 import file mismatch 消失。
- [x] 3.2 运行 `pytest --collect-only` 与 `pytest -q` 全量门禁。
- [x] 3.3 更新 `docs/DEVELOPMENT_STATUS.md`，记录测试收集契约和验证结果。

<!-- review skipped: multi-agent dispatch not authorized; main-session scope review found no critical or important issues -->
