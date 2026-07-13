## Why

搜索编排把属性搜索、向量搜索、融合、低置信度降级、Critic 迭代和结果裁剪集中在多个长函数中，重复的结果转换与异常处理分支使流程难以审查。搜索、嵌入和属性模块之间的职责边界也不够清晰，增加了维护和测试成本。

## What Changes

- 拆分搜索路由、结果归一化、融合排序、Critic 迭代和最终裁剪职责。
- 收敛 `search.py`、`embed_search.py` 和 `attribute_search.py` 中重复的结果转换与降级处理。
- 保留现有搜索输入输出模型、排序语义、阈值、Critic 开关和注册工具入口。
- 为统一后的边界补充单元和流程测试，覆盖成功、空结果、低置信度和依赖失败路径。

## Capabilities

### New Capabilities

- `search-orchestration-maintainability`: 为多路径搜索提供清晰、可测试且行为稳定的内部编排边界。

### Modified Capabilities

无。此 change 不改变搜索 API 或结果语义。

## Impact

- 影响 `src/vsa_agent/tools/search.py`、`embed_search.py`、`attribute_search.py`、相关代理和测试。
- 需要验证属性-only、向量-only、融合、Critic 重试、低置信度回退和异常继续执行行为。
- 不改变公共 API、数据模型、索引结构或外部检索服务契约。
