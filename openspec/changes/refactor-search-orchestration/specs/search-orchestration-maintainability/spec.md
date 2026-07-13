## ADDED Requirements

### Requirement: 搜索公开契约保持
搜索编排重构 MUST 保留现有输入模型、最终 `SearchOutput`、工具注册入口和 API 行为。

#### Scenario: 执行现有搜索入口
- **WHEN** 调用者使用属性、向量或融合搜索路径
- **THEN** 最终结果类型、排序语义和 top_k 裁剪 MUST 与重构前一致

### Requirement: 搜索结果统一归一化
编排层 SHALL 使用单一边界把受支持的搜索返回形状转换为 `SearchResult` 列表。

#### Scenario: 处理受支持结果形状
- **WHEN** 外部搜索返回 `SearchOutput`、带 `data` 的对象或受支持列表
- **THEN** 编排层 MUST 产生语义一致的结果列表供后续阶段使用

### Requirement: Critic 行为保持
Critic 验证 SHALL 仅在配置、请求和可用代理均允许时执行，并保持现有失败降级行为。

#### Scenario: Critic 依赖失败
- **WHEN** Critic 已启用但调用抛出异常
- **THEN** 搜索 MUST 记录失败并继续返回基础检索结果

#### Scenario: Critic 未启用
- **WHEN** 任一启用条件不满足
- **THEN** 编排层 MUST NOT 调用 Critic

### Requirement: 搜索阶段异常可定位
外部依赖异常 SHALL 包含搜索阶段上下文，且纯转换错误 MUST NOT 被无上下文静默吞掉。

#### Scenario: 外部搜索失败
- **WHEN** 属性或向量搜索依赖抛出异常
- **THEN** 日志 MUST 标识失败阶段，并按该路径现有降级契约继续或返回空结果
