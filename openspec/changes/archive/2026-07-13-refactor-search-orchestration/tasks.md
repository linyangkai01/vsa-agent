## 1. Characterization 测试

- [x] 1.1 覆盖 `SearchOutput`、带 `data` 对象和列表三种受支持结果形状及空结果。
- [x] 1.2 覆盖属性-only、向量-only、融合、低置信度、top_k 和去重排序行为。
- [x] 1.3 覆盖 Critic 未启用、确认、拒绝、重试和异常降级时的消息顺序与最终结果。

## 2. 提取纯搜索规则

- [x] 2.1 实现单一结果归一化边界，并迁移重复的 `.data`/列表转换。
- [x] 2.2 提取去重、置信度回退、融合排序和最终裁剪纯函数。
- [x] 2.3 为每个纯函数运行表驱动测试，确认排序与分数语义不变。

## 3. 拆分外部阶段

- [x] 3.1 保留属性、向量和融合搜索的显式外部阶段边界，并用纯路由/归一化 helper 收敛重复规则。
- [x] 3.2 提取 Critic 启用与结果过滤纯规则，保留独立调用、迭代状态与失败继续行为。
- [x] 3.3 将宽泛异常保留在外部依赖边界，并保持现有降级结果与阶段日志语义。

## 4. 集成与验证

- [x] 4.1 将 `execute_core_search` 收敛为阶段协调 facade，保持公共 import、注册入口和进度输出顺序。
- [x] 4.2 运行 search/embed/attribute 工具、search agent、API 与 acceptance 测试。
- [x] 4.3 运行 Ruff 门禁和全量 `pytest -q`，并更新 `docs/DEVELOPMENT_STATUS.md` 的架构与验证状态。

<!-- review skipped: multi-agent execution was not authorized for this run -->
