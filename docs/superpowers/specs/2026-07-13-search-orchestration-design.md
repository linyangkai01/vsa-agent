---
comet_change: refactor-search-orchestration
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-13-refactor-search-orchestration
status: final
---

# 搜索编排重构技术设计

## 当前问题与边界

`search.py` 同时包含 Pydantic 模型、查询分解、异步生成器、结果形状判断、路由、融合、critic 和注册工具。外部调用必须继续留在具有日志和异常上下文的边界，但结果选择规则可以独立为纯函数。

`SearchResult` 与 `SearchOutput` 继续定义在 `search.py`，避免改动 50 多个调用点。新纯模块不导入 facade 模型，而是只读取受支持对象的 `.data`、结果的 `video_name`、`similarity` 和 `sensor_id` 属性；这样不会形成循环依赖。

## 纯规则模块

新增 `src/vsa_agent/tools/search_pipeline.py`，提供：

- `select_search_route(has_action, attributes, attribute_available)`：精确复现 attribute-only、embed-only、fusion 和无可执行路径的判断。
- `normalize_search_results(value)`：把列表或带 `.data` 的对象复制为列表；`None` 和不支持形状返回空列表。
- `rank_unique_results(results)`：按 `video_name` 保留最高 similarity，再按 similarity 降序。
- `select_fusion_results(embed_results, attribute_results, confidence_threshold)`：embed 结果低于正阈值时回退属性结果，否则合并去重排序。
- `max_similarity(results)`：为空返回 `None`，供进度消息判断。
- `filter_rejected_sensors(results, rejected_video_infos)`：保持顺序地移除已拒绝 sensor。
- `trim_search_results(results, top_k)`：集中最终裁剪。
- `should_apply_critic(...)`：保留原启用条件，并由 facade 重导出相同对象。

所有 helper 返回新列表，不修改调用者输入。

## Facade 集成

`execute_core_search` 继续控制进度消息和外部异常：

1. 查询分解后调用 `select_search_route`。
2. 各外部 search 调用仍包裹阶段化日志，成功结果统一交给 `normalize_search_results`。
3. embed 低置信度消息通过 `max_similarity` 生成。
4. fusion 结果通过 `select_fusion_results` 选择。
5. critic 输入、调用、计数和重试保持原结构，只用 `filter_rejected_sensors` 处理结果。
6. 最终通过 `trim_search_results` 构造 `SearchOutput`。

`fusion_search_rerank`、`_run_attribute_only_search` 和注册 `search_tool` 复用结果归一化与去重 helper，消除 `.data`/list 判断重复。现有 weighted/RRF 公式、阈值默认值、top_k、注册名称和异常日志文本不改变。

## 兼容与异常

- `should_apply_critic` 从 `search.py` 继续可导入。
- `execute_core_search` 仍是 async generator，消息顺序不变。
- 外部 attribute/embed/critic 异常继续在 facade 记录具体阶段并按原路径降级。
- 纯函数不捕获属性错误；只有明确支持的结果形状进入纯规则。
- 不修改 `embed_search.py`、`attribute_search.py` 的后端协议，只让编排层统一消费结果。

## 测试策略

1. Red：直接导入不存在的 `search_pipeline` 并用表驱动测试锁定路由、三种结果形状、空值、去重、低置信度、critic 过滤和裁剪。
2. Green：实现纯模块，先跑纯测试。
3. 集成：接入 `execute_core_search`、fusion rerank、attribute-only 和 `search_tool`，运行完整 search 工具测试。
4. 路径矩阵：运行 embed、attribute、search agent、API 与 acceptance。
5. 门禁：compileall、Ruff、全量 pytest。

## 回滚

若消息顺序或排序语义漂移，将 helper 逻辑内联回 `search.py`；无数据、索引或 API 迁移。
