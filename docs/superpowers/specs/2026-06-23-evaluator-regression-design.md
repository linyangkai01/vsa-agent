# Evaluator Regression Design

**Date:** 2026-06-23

**Goal**

为现有 `evaluators/` 子系统补一条可批量执行的 acceptance 回归入口，同时保留最终阶段接入真实模型 API 的效果验证能力。

## Scope

本设计只覆盖 evaluator 回归入口，不重做现有 acceptance 测试体系，不引入新的测试框架，也不把真实模型调用混入默认回归。

包含两层验证：

1. 离线确定性回归
   - 使用固定 fixtures
   - 调用现有 `evaluate_understanding_result()`、`evaluate_search_output()`、`evaluate_report_markdown()`
   - 作为默认 acceptance 回归的一部分

2. 真实模型 API 效果验证
   - 只在显式提供环境变量时运行
   - 使用少量高价值样例
   - 目标是观察真实输出质量与 evaluator 分数是否一致

## Non-Goals

- 不做 LLM-as-judge
- 不做新的 CLI 工具
- 不做复杂的多目录 fixture registry
- 不把所有现有 acceptance 用例都迁移到 evaluator fixture 格式

## Recommended Approach

### Approach A: Fixture-driven pytest regression entry

在 `tests/acceptance/fixtures/` 中保存少量结构化样例，新增一个 pytest 文件统一加载 fixtures、分发到对应 evaluator、断言 `passed` 与分数字段。

优点：
- 与现有 pytest/acceptance 体系一致
- 日常运行稳定且便宜
- 后续扩样例只需加 fixture

缺点：
- 需要补一个很小的 fixture schema 和 loader

### Approach B: Inline assertions inside existing acceptance tests

在现有 `test_search_flow.py`、`test_report_flow.py` 中直接手写 evaluator 调用。

优点：
- 短期改动更少

缺点：
- 规则分散
- 不利于批量扩展和统一执行

### Approach C: Standalone script runner

增加单独脚本读取 fixture 并输出 evaluator 分数。

优点：
- 方便手工执行

缺点：
- 脱离现有 pytest 入口
- 当前阶段收益不高

### Decision

采用 Approach A。

## Architecture

### 1. Fixture format

新增一个最小 JSON fixture 文件，例如：

- `tests/acceptance/fixtures/evaluator_regression.json`

文件包含一个样例数组，每个样例显式声明：

- `name`
- `evaluator_type`: `understanding | search | report`
- `actual`
- `expected`

其中：

- `understanding.actual` 使用 `UnderstandingResult` 兼容结构
- `search.actual` 使用 `SearchOutput` 兼容结构
- `report.actual` 使用 markdown 字符串
- `expected` 直接映射到现有 evaluator 的 expected models / arguments

### 2. Loader and dispatch

新增一个小的 fixture loader，负责：

- 读取 JSON
- 按 `evaluator_type` 分发
- 把字典转换为对应 Pydantic 模型或原生参数

不引入新的生产代码模块；先放在测试侧，避免为了测试入口扩张运行时代码面。

### 3. Offline regression test

新增：

- `tests/acceptance/test_evaluator_regression.py`

职责：

- 加载 fixtures
- 参数化执行每个样例
- 调用现有 evaluator
- 断言 `EvaluationResult.passed is True`
- 必要时断言 `score >= min_score`

### 4. Real API effect validation

新增一条单独 acceptance 测试入口，例如：

- `tests/acceptance/test_evaluator_live_api.py`

职责：

- 检查是否存在真实模型环境变量
- 未配置时 `pytest.skip()`
- 已配置时调用现有真实链路，拿到真实输出
- 用 evaluator 对真实输出打分
- 断言最小可接受分数阈值

这条测试只放少量代表样例，避免成本和波动失控。

## Data Flow

### Offline

`fixture json -> loader -> evaluator dispatch -> EvaluationResult -> pytest assertions`

### Live API

`live test input -> existing real tool/agent path -> real model output -> evaluator -> pytest assertions`

## Error Handling

- fixture 缺字段时直接让测试失败，不做隐式容错
- 未知 `evaluator_type` 直接抛错
- live API 环境变量缺失时跳过，不判失败
- live API 调用失败时测试失败，保留原始异常，方便定位

## Testing Strategy

先做最小闭环：

1. 一个 `understanding` fixture
2. 一个 `search` fixture
3. 一个 `report` fixture
4. 一个离线回归 pytest 入口
5. 一个默认跳过的 live API 入口

## Success Criteria

- 默认运行时，离线 evaluator regression 可稳定通过
- 未配置真实模型环境变量时，live API 测试明确 skip
- 配置真实模型环境变量后，live API 测试可以跑通至少一条代表样例
- 现有 evaluator 模块无需修改总体接口即可复用
