# Phase 8B 检索问答闭环设计

> 范围：`agents/search_agent.py`、`tools/search.py`、`tools/incidents.py`、`tools/vss_summarize.py`、`agents/critic_agent.py`，以及相关单元测试与验收测试
> 日期：2026-06-19
> 目标：将检索问答链正式收敛为“query -> search -> optional critic -> incidents -> summarize -> answer”的稳定业务闭环。

## 一、背景

Phase 8A1 已经把“单视频分析报告闭环”从工具拼装状态提升为稳定的业务主链，说明当前项目已经具备进入“能力闭环阶段”的条件。

在搜索侧，项目当前也已经具备多块基础能力：

- `tools/search.py` 已实现三路径搜索
- `agents/search_agent.py` 已实现面向业务的搜索编排入口
- `agents/critic_agent.py` 已实现基于 VLM 的结果确认/拒绝逻辑
- `tools/incidents.py` 已能将 `SearchOutput` 标准化为 `Incident[]`
- `tools/vss_summarize.py` 已能把结构化结果转换为文本摘要

也就是说，搜索侧并不缺“模块存在性”，缺的是把这些模块真正拉成一条可交付、可验收、可说明的业务链。

因此 Phase 8B 的目标，不是再补一个 search helper，也不是继续扩工具层，而是把“检索命中如何变成用户可消费回答”这件事正式主链化。

## 二、现状问题

### 1. `search_agent` 当前停在“返回搜索结果”层

现在的 `agents/search_agent.py` 已经能：

- 接收 `SearchAgentInput`
- 做 query decomposition
- 调度三路径搜索
- 在部分路径里尝试 critic

但它对外更像“搜索结果列表入口”，还没有真正承担“把搜索结果转成最终回答”的职责。

### 2. `incidents` 与 `vss_summarize` 还没有进入搜索主链

`tools/incidents.py` 和 `tools/vss_summarize.py` 都存在，但它们和搜索链之间还没有被正式定义成主链关系。

这会带来两个问题：

- 搜索命中如何转换成业务语义对象，没有被稳定锁住
- 最终给用户的回答文本如何生成，也没有统一出口

### 3. critic 语义当前更像“能力存在”，不是“闭环契约”

当前代码里，critic 已经能运行，但其业务位置还不够清楚：

- 是否默认启用？
- critic 失败时主链是否降级？
- critic 的结果如何影响最终回答？
- critic 是否应写入 metadata？

这些问题如果不先定义清楚，后面接入 `top_agent`、API、聊天入口时，很容易出现每个入口各自处理一次的情况。

### 4. 现有验收测试偏轻，不能证明“检索问答闭环”

当前搜索和 critic 的验收测试更偏向“模块能跑”：

- query decomposition 能执行
- embed/fusion 路径能返回结果
- critic 能确认/拒绝

但还缺少以下闭环层面的保证：

- 搜索结果会不会稳定转成 incidents
- incidents 会不会稳定转成最终回答
- critic 可选启用时是否真的影响主链
- critic 出错时主链是否降级而不是炸掉

## 三、业务位置

Phase 8B 位于“用户提出检索问题”和“系统返回最终回答”之间，是最核心的问答型搜索主链。

目标业务流如下：

1. 用户输入 query
2. `search_agent` 调用搜索执行层
3. 搜索执行层根据 decomposition 走 embed / attribute / fusion 路径
4. 如显式启用 critic，则在结果层做验证
5. 搜索结果统一转换为 `Incident[]`
6. 将标准化事件结果转换为最终文本回答
7. 返回文本回答、结构化结果和运行元数据

这条链是后续以下能力的共同基础：

- `top_agent` 的搜索问答调用
- API / 聊天入口的检索回答
- 检索结果报告化
- 搜索结果进一步进入报告/审校链

## 四、设计目标

本子项目的设计目标如下：

1. 将搜索问答内部主链正式定义为：
   `query -> search -> optional critic -> incidents -> summarize -> answer`
2. 将 `critic` 明确为可选增强层，而不是默认强制层
3. 让 `incidents` 和 `vss_summarize` 正式进入搜索主链
4. 保持现有对外接口尽量不破坏
5. 用单元测试和验收测试锁定默认成功流、critic 成功流、critic 降级流、空结果流

非目标：

- 本轮不接 `top_agent`
- 不纳入 `/api/chat` 或其他 API/聊天入口
- 不推进真实 ES 深接入
- 不推进更真实 VST / 时间锚点语义

## 五、候选方案

### 方案 A：最小串联

做法：

- 保留 `search_agent` 当前语义
- 在外层再包一层 `incidents + summarize`

优点：

- 改动小
- 很快能形成一轮功能闭环

缺点：

- `search_agent` 仍然停留在“结果列表层”
- `incidents` / `summarize` 仍然像旁路工具
- 后续接 `top_agent` / API 时还会返工

### 方案 B：搜索结果主链化（本轮采用）

做法：

- `search_agent` 负责组织完整问答主链
- `tools/search.py` 只负责搜索执行与可选 critic 路由
- `incidents` 负责统一标准化
- `vss_summarize` 负责产出用户可读回答
- 最终返回“文本回答 + 结构化结果 + 元数据”

优点：

- 最符合“业务闭环”的目标
- 搜索侧主链职责最清楚
- 后续接 `top_agent`、API 最顺滑

缺点：

- 需要明确搜索回答的内部契约
- 需要补更多协作测试

### 方案 C：先只收 `tools/search.py`

做法：

- 先把三路径搜索和 critic 语义完全收紧在 `tools/search.py`
- `search_agent` 暂不升级成完整问答主链

优点：

- 范围小
- 容易集中处理搜索算法行为

缺点：

- 不能真正解决“结果如何变成回答”的主链问题
- `incidents` / `summarize` 仍然没有进入业务闭环

## 六、最终方案

本轮采用方案 B：搜索结果主链化。

核心判断：

- 当前并不缺搜索模块，而是缺问答型业务主链
- `critic`、`incidents`、`summarize` 都已存在，最合适的是把它们组织起来
- 只有形成稳定的内部问答闭环，后续接 `top_agent` 和 API 才不会重复造胶水

## 七、模块职责设计

### 1. `agents/search_agent.py`

角色：编排器

职责：

- 接收 `SearchAgentInput`
- 组织 decomposition、搜索执行、可选 critic、incidents 标准化、摘要生成
- 返回文本回答、结构化结果与元数据

约束：

- 不负责具体搜索融合算法
- 不负责 incidents 映射细节
- 不负责 critic 判定细节

### 2. `tools/search.py`

角色：搜索执行层

职责：

- 承载三路径搜索
- 组织 embed-only / attribute-only / fusion 路径
- 在显式条件下接入 critic
- 输出 `SearchOutput`

约束：

- 不负责最终用户回答组织
- 不负责 incidents 文本展示

### 3. `tools/incidents.py`

角色：标准化层

职责：

- `SearchOutput -> list[Incident]`
- 提供搜索结果到事件表达的统一映射

这是搜索链进入业务语义层的第一跳。

### 4. `tools/vss_summarize.py`

角色：摘要层

职责：

- 将标准化后的搜索结果转换为用户可读文本
- 提供“最终回答文本”的稳定出口

本轮可能需要为搜索侧增加最小适配入口，但不重做整套摘要逻辑。

### 5. `agents/critic_agent.py`

角色：可选验证层

职责：

- 仅在 `use_critic=True` 时介入
- 对搜索命中做确认/拒绝
- 输出结果验证信息

约束：

- critic 出错时不能炸掉搜索主链
- critic 的参与状态必须通过 metadata 显式表达

## 八、数据流设计

主数据流固定为：

```text
SearchAgentInput
  -> decompose_query(...) [optional]
  -> execute_search(...) / execute_core_search_wrapper(...)
  -> SearchOutput
  -> optional critic verification
  -> search_output_to_incidents(...)
  -> summarize(...)
  -> text answer + structured results + metadata
```

其中最重要的约束有三个：

1. `critic` 是可选分支，不是默认强制分支
2. `incidents` 和 `summarize` 是主链成员，不再是旁路工具
3. 搜索主资产是 `SearchOutput`，critic 和 summarize 是增强层，增强失败时应优先降级而不是整链失败

## 九、错误语义

### 1. 输入错误

示例：

- query 为空
- max_results 非法

策略：

- 直接抛 `ValueError`
- 不进入搜索主链

### 2. 搜索执行错误

示例：

- embed search 失败
- attribute search 失败
- query decomposition 失败

策略：

- decomposition 失败时降级为原 query
- 单一路径失败时优先降级为空结果或部分结果
- 不轻易把整条链直接炸掉

### 3. critic 错误

示例：

- critic 不可用
- critic 模型调用失败
- critic 返回结构非法

策略：

- 视为“critic 未生效”
- 搜索主链继续返回结果
- metadata 显式记录：
  - `critic_requested`
  - `critic_applied`
  - `critic_error`

### 4. 摘要/标准化错误

示例：

- incidents 转换失败
- summarize 阶段失败

策略：

- 优先返回基础搜索结果
- 文本回答允许降级成简单结果列表摘要
- 不因为润色层失败而丢失搜索命中

## 十、测试与验收设计

### 1. 单元测试

重点文件：

- `tests/unit/agents/test_search_agent.py`
- `tests/unit/tools/test_search.py`
- `tests/unit/tools/test_incidents.py`
- `tests/unit/tools/test_vss_summarize.py`

覆盖重点：

- `search_agent`
  - 默认主链会把 `SearchOutput` 送入 `incidents`
  - 默认主链会生成最终文本回答
  - `use_critic=False` 时不调用 critic
  - `use_critic=True` 时才尝试调用 critic
  - critic 出错时主链继续返回结果并记录 metadata

- `tools/search.py`
  - embed-only / attribute-only / fusion 三路径
  - `use_critic` 与 `enable_critic` 的组合行为
  - 空结果与异常降级语义

- `incidents.py`
  - `SearchOutput -> Incident[]`
  - 时间字段、描述字段、类别字段映射正确
  - 空输入和宽松输入兼容

- `vss_summarize.py`
  - 有结果时生成稳定文本
  - 无结果时生成稳定空回答
  - 多事件摘要顺序稳定

### 2. 组件级测试

重点锁模块协作：

- `search_agent` 会把搜索结果送进 `incidents`
- `search_agent` 会把标准化结果送进摘要层
- `critic` 不参与时主链照常完成
- `critic` 出错时只影响增强信息，不打断主链

### 3. 验收测试

重点文件：

- `tests/acceptance/test_search_flow.py`
- `tests/acceptance/test_critic_flow.py`

建议锁定四类场景：

1. 默认无 critic 成功流
2. 显式启用 critic 成功流
3. critic 失败降级流
4. 空结果流

## 十一、完成标准

满足以下条件，即可认为本子项目完成：

1. 搜索问答内部主链固定为：
   `query -> search -> optional critic -> incidents -> summarize -> answer`
2. `critic` 成为显式可选增强层
3. `incidents` 和 `vss_summarize` 正式进入搜索主链
4. 验收测试可以证明：
   - 默认成功流
   - critic 成功流
   - critic 降级流
   - 空结果流
5. 保持现有对外接口尽量不破坏

## 十二、实施顺序建议

建议按以下顺序进入实现：

1. 先补验收测试，锁定默认成功流与 critic 可选流
2. 再收口 `search_agent` 的编排职责
3. 再收口 `critic` 的可选增强语义与 metadata
4. 最后补 incidents / summarize 的最终回答出口

这样可以最大程度保证我们是在“用测试拉搜索问答闭环”，而不是先改一堆搜索细节，再回头拼业务链。
