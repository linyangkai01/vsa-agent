## Why

全量 `pytest` 当前在收集阶段失败：`tests/unit/archive/test_models.py` 与 `tests/unit/recorded_video/test_models.py` 具有相同模块名，但所在目录没有包初始化文件。两个文件单独运行都通过，组合运行却产生导入模块错配，导致测试门禁不能反映真实结果。

## What Changes

- 建立稳定、唯一的测试模块导入边界。
- 修复重复测试模块名导致的收集冲突。
- 保留现有测试语义和断言强度，不通过跳过测试掩盖失败。
- 为测试收集契约增加回归覆盖。

## Capabilities

### New Capabilities

- `test-collection-stability`: 保证仓库测试可被全量收集且模块身份确定。

### Modified Capabilities

无。此 change 不改变生产能力要求。

## Impact

- 影响 `tests/` 的包结构、pytest 收集配置和测试入口。
- 解除全量测试收集阻断，为后续质量基线和重构提供可靠验证门禁。
- 不修改 `src/` 运行时行为、公共 API 或数据模型。
