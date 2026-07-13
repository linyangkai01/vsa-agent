## ADDED Requirements

### Requirement: 测试模块身份唯一
测试系统 SHALL 为不同测试子目录中的同名 Python 文件分配不同的模块身份。

#### Scenario: 同名测试文件共同收集
- **WHEN** pytest 同时收集 `tests/unit/archive/test_models.py` 和 `tests/unit/recorded_video/test_models.py`
- **THEN** 两个文件 MUST 以不同模块身份完成收集且不出现 import file mismatch

### Requirement: 执行范围结果一致
测试系统 SHALL 保持单文件执行与全量执行的测试语义一致。

#### Scenario: 单文件与全量执行
- **WHEN** 分别执行冲突文件并随后执行全量测试
- **THEN** 单文件中可通过的测试 MUST 在全量执行中被同样收集和执行

### Requirement: 禁止掩盖收集失败
测试稳定化 MUST NOT 通过跳过测试、降低断言或排除测试目录实现。

#### Scenario: 验证修复方式
- **WHEN** 测试收集冲突被修复
- **THEN** 两个原始测试文件及其断言 MUST 仍保留在默认测试范围内
