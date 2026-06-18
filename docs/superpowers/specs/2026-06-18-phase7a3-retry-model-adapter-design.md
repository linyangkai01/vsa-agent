# Phase 7A3 重试基础设施与 Model Adapter 对齐设计

> 范围：`utils/retry.py`、`model_adapter/base.py`、`model_adapter/openai_adapter.py`、`model_adapter/vllm_adapter.py`
> 日期：2026-06-18
> 目标：补齐与原版思路一致的统一重试基础设施，并将其稳定接入模型调用主链，在不改变现有对外接口的前提下提升调用可靠性与测试完备度。

## 一、背景

到 Phase 7A2 为止，项目已经完成了两层基础设施对齐：

1. A1：`prompt.py`、`reasoning_parsing.py`、`reasoning_utils.py`、`asyncmixin.py`
2. A2：`data_models/vss.py`、`time_convert.py`、`frame_select.py`

这两轮解决的是“提示词/推理契约”和“时间/帧/模型基础数据契约”。

当前剩余的基础设施短板里，最值得优先补齐的是 `retry.py + model_adapter` 这一组。原因很直接：

- 它在已有审计文档里被反复标为 P1
- 它位于所有 LLM/VLM 调用链的公共入口
- 它不是单一工具内部逻辑，而是跨 `video_understanding`、后续 `agent`、报告链都能复用的基础设施
- 现在仓库虽然已经有 `utils/retry.py`，但它还没有成为 model adapter 的统一契约

换句话说，A3 不是“再补一个工具文件”，而是把“模型调用失败时系统应该如何重试”这件事，收口成可复用、可测试、可推理的公共能力。

## 二、现状问题

当前实现存在四类问题：

### 1. `retry.py` 存在，但只是一个局部装饰器

`src/vsa_agent/utils/retry.py` 已经提供了 `async_retry(...)`，但它目前是偏轻量实现：

- 只有装饰器形态
- 不暴露统一策略对象或更明确的异常/日志契约
- 没有和 model adapter 主链形成稳定约定

这意味着“是否重试、重试几次、日志怎么打、异常怎么传播”仍然分散在调用方理解里。

### 2. `openai_adapter` 与 `vllm_adapter` 的重试行为不一致

当前：

- `OpenAIModelAdapter` 依赖 `ChatOpenAI(..., max_retries=2)`
- `VLLMModelAdapter` 没有显式配置同等重试契约

这会带来两个问题：

1. 重试行为受底层 SDK 默认语义影响，仓库自己的测试难以锁定
2. 两个 adapter 的失败恢复逻辑不对齐，后续调用方无法假设一致性

### 3. `BaseModelAdapter` 没有表达“统一重试能力”这个接口层语义

当前 `BaseModelAdapter` 只定义：

- `invoke(messages)`
- `astream(messages)`
- `bind_tools(tools)`

但没有把“模型调用的稳定性策略”表达为基类契约的一部分。

这不是说要在对外接口里新增复杂方法，而是要让内部实现层形成统一约定：子类的 `invoke()` 不是直接裸调底层 SDK，而是要走共享重试语义。

### 4. 测试覆盖只验证了“能实例化”，没有验证“失败恢复”

现有 `tests/unit/model_adapter/test_model_adapter.py` 主要覆盖：

- factory 是否返回 adapter
- adapter 是否能实例化
- `bind_tools()` 是否委托底层 llm

缺口在于没有验证：

- `invoke()` 遇到瞬时失败时是否会重试
- 达到上限后是否原样抛出异常
- `astream()` 是否错误地吞掉异常
- 底层 SDK 的重试参数和我们自己的 retry 策略是否发生冲突

## 三、设计目标

Phase 7A3 的设计目标如下：

1. 保持现有外部接口不变  
   外部仍通过 `adapter.invoke(messages)` / `adapter.astream(messages)` 使用 adapter，不新增破坏性签名。

2. 把“调用重试”收口为仓库自己的共享能力  
   不再把核心语义交给底层 SDK 默认行为。

3. 对齐 OpenAI / vLLM 两类 adapter 的失败恢复语义  
   至少在 `invoke()` 层保持一致。

4. 对 `astream()` 的策略保持保守  
   本阶段不做复杂流式重放；流式链路以“异常透明传播”为主，不错误吞异常、不伪造重试流。

5. 用测试先锁定语义，再补实现  
   这轮必须继续遵守 TDD，而不是直接改 adapter。

## 四、候选方案

### 方案 A：继续依赖底层 `ChatOpenAI.max_retries`

做法：

- `OpenAIModelAdapter` 保留 `max_retries`
- `VLLMModelAdapter` 补同类参数
- 不把 `utils/retry.py` 接入 adapter 主链

优点：

- 改动小
- 很快能“看起来有重试”

缺点：

- 重试语义依赖第三方库
- 单元测试难以稳定验证
- adapter 之间仍然容易出现细微语义漂移
- 与“仓库内部统一基础设施”目标不一致

### 方案 B：以 `utils/retry.py` 为唯一公共重试入口，对齐 `invoke()` 主链（推荐）

做法：

- 补强 `utils/retry.py`
- adapter 的 `invoke()` 统一通过共享重试装饰器或共享重试包装执行
- `astream()` 暂不做自动重放，只保证透明传播异常
- 对底层 SDK 的 `max_retries` 采取收紧策略，避免双重重试

优点：

- 语义清晰
- 测试稳定
- OpenAI / vLLM 行为一致
- 后续其他 adapter 能直接复用

缺点：

- 需要改到 adapter 主链
- 需要额外处理“避免双重重试”

### 方案 C：引入更重的 RetryPolicy 对象层

做法：

- 新增独立 `RetryPolicy` / `RetryExecutor`
- adapter 持有策略对象
- 将来可扩展超时、熔断、指标

优点：

- 扩展性最好

缺点：

- 对当前项目阶段偏重
- 会把 Phase 7A3 做得过大

## 五、最终选择

本阶段采用 **方案 B**。

理由很简单：它既能真正解决当前 P1 缺口，又不会把基础设施抽象做过头。我们需要的是“稳定、统一、可测试”的重试能力，而不是为了优雅再造一个完整策略框架。

## 六、模块设计

### 1. `utils/retry.py`

职责：

- 提供共享异步重试能力
- 对外继续保留 `async_retry(...)`
- 明确以下契约：
  - 最大重试次数语义
  - 延迟与退避倍数语义
  - 可捕获异常白名单
  - 最终异常原样抛出

本阶段不新增复杂全局配置读取，先保持显式参数。

### 2. `model_adapter/base.py`

职责：

- 继续作为公共 adapter 抽象基类
- 不改公开抽象方法签名
- 增加一个内部共享入口，例如受保护包装方法或统一约定，表达“invoke 需要走共享 retry”

关键点：

- 不让基类膨胀成策略中心
- 只表达内部契约，不扩大公共表面

### 3. `openai_adapter.py`

职责：

- 继续封装 `ChatOpenAI`
- `invoke()` 改为走共享 retry 包装
- `astream()` 维持当前透明流式转发
- `bind_tools()` 保持兼容

设计要点：

- 底层 `ChatOpenAI` 的 `max_retries` 需要收紧，避免和我们自己的 retry 重叠
- 若底层已经做轻量连接级重试，需以“仓库自己的语义可测试”为优先

### 4. `vllm_adapter.py`

职责：

- 与 `openai_adapter.py` 保持同构
- `invoke()` 使用同一套共享 retry 语义
- `astream()` 保持保守透明

## 七、数据流

Phase 7A3 完成后，模型调用路径变为：

1. 业务模块调用 `adapter.invoke(messages)`
2. adapter 内部进入共享 retry 包装
3. retry 包装调用底层 `self.llm.ainvoke(messages)`
4. 若命中可重试异常：
   - 记录 warning 日志
   - 按退避策略等待
   - 再次尝试
5. 若达到上限：
   - 原样抛出最后一次异常
6. 若成功：
   - 返回底层消息对象

其中 `astream()` 暂时不进入自动重试闭环，避免流式部分输出与重放语义混乱。

## 八、错误处理策略

本阶段的错误处理策略如下：

1. `invoke()`  
   - 对配置的异常类型执行重试
   - 达到上限后抛出最后一次异常
   - 不吞异常，不改异常类型

2. `astream()`  
   - 不自动重试
   - 直接传播底层异常

3. `bind_tools()`  
   - 保持现有语义，不引入额外错误包装

## 九、测试策略

测试分两层。

### 1. `tests/unit/utils/test_retry.py`

覆盖：

- 首次成功不重试
- 一次失败后恢复
- 超过上限后抛错
- 非白名单异常不重试
- 退避等待参数是否被正确使用

### 2. `tests/unit/model_adapter/test_model_adapter.py`

覆盖：

- `OpenAIModelAdapter.invoke()` 在瞬时失败后会重试
- `VLLMModelAdapter.invoke()` 在瞬时失败后会重试
- 两者达到上限后抛出原异常
- `astream()` 异常透明传播
- `bind_tools()` 保持现有行为
- adapter 初始化时避免把仓库重试和底层 SDK 重试叠加成双重语义

## 十、非目标

本阶段不做以下内容：

- 不重构 factory 模块的大结构
- 不做流式输出自动重放
- 不引入熔断器、全局遥测、指标系统
- 不新增新的配置文件层级来驱动 retry
- 不改业务工具调用 adapter 的外部方式

## 十一、验收标准

完成标准如下：

1. `utils/retry.py` 的契约被更完整测试锁定
2. `openai_adapter.py` 与 `vllm_adapter.py` 的 `invoke()` 都走统一 retry 语义
3. `astream()` 不做危险的自动重放，异常透明传播
4. 现有对外接口不变
5. Phase 7A3 相关单测全部通过
6. 唯一总计划文档同步记录 A3 状态

