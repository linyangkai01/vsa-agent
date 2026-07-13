---
comet_change: refactor-video-understanding-pipeline
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-13-refactor-video-understanding-pipeline
status: final
---

# 视频理解管线重构技术设计

## 当前边界

`video_understanding.py` 同时包含纯转换和运行时编排。现有 `_extract_frames`、`_analyze_frames`、`_resolve_video_source`、`analyze_video_segment`、`analyze_video` 与 `analyze_long_video` 已形成可 monkeypatch 的 I/O 边界，测试和外部模块依赖这些名称。直接搬迁它们会用文件拆分换来兼容层和动态派发复杂度，收益不足。

真正可独立、无 I/O 且内聚的区域是：

- `_normalize_timestamp` 与 `_timestamp_to_seconds`；
- `_parse_thinking_from_content`；
- 证据字段选择与 `EvidenceRef` 构造；
- 时间标签到 `DetectedEvent` 的转换；
- 字符串、字典和既有 `UnderstandingResult` 到统一结果的转换。

## 模块设计

新增 `src/vsa_agent/tools/video_understanding_normalization.py`。模块只依赖共享数据模型、`parse_reasoning_content` 和时间工具，不依赖 cv2、网络客户端、配置单例、模型 adapter 或 trace/artifact 写入。

模块保留现有 helper 签名，并新增内部 `_build_evidence`，统一文件视频和 RTSP 的互斥字段：文件证据只设置 `video_path`，RTSP 证据只设置 `sensor_id`。`_normalize_model_response` 继续原样处理三条路径：既有结果直接返回；字典补默认 query/source 后校验；字符串构造 chunk、事件和 metadata。

`video_understanding.py` 从纯模块显式导入原 helper 名称，因此既有 `from ...video_understanding import _normalize_model_response` 继续可用。facade 内部也使用这些导入名，行为和 patch 位置稳定。`lvs_video_understanding.py` 改为从纯模块导入 `_timestamp_to_seconds`，消除它为了一个纯函数反向依赖整个 facade 的关系。

## I/O 编排

帧获取/编码、VLM 调用、source resolution 和短长视频路由继续留在 facade，但在结构上只消费纯模块结果。现有函数参数已经提供 model adapter、config 和 source/time 输入，并被测试作为注入点使用；本 change 不再添加容器或协议层。

artifact 和 trace 写入继续位于 `analyze_video_segment` 的模型调用之后、结果返回之前。异常类型、重试、长视频阈值、prompt、metadata 字段和旧文本返回不改变。

## 兼容与风险控制

- facade 导入的 helper 对象与纯模块对象相同，避免双实现漂移。
- 不更改公共工具签名、Pydantic 模型或注册装饰器。
- 不移动动态派发函数，保留所有现有 monkeypatch 路径。
- LVS 只复用时间转换，不合并其 sensor、source type 或 chunk 语义。

## 测试策略

1. 先通过新测试从纯模块导入 helper，并断言模块不暴露 cv2、配置或 trace 依赖；实现前应失败。
2. 对字符串、字典、既有结果、文件证据、RTSP 证据和 reasoning 过滤做结构断言。
3. 断言 facade helper 与纯模块 helper 为同一对象，锁定兼容路径。
4. 运行视频理解、live trace、LVS、共享数据模型和 acceptance 测试。
5. 运行 Ruff、compileall 和全量 pytest。

## 回滚

若出现行为漂移，将纯函数移回 facade 并恢复 LVS import；没有数据迁移或外部协议变更。
