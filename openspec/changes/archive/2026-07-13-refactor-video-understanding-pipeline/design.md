## Context

`video_understanding.py` 同时承担配置解析、时间参数规范化、模型响应解析、证据/事件构造、帧编码、VLM 调用、长视频路由、RTSP 解析、artifact/trace 记录和工具兼容返回。`lvs_video_understanding.py` 又包含相邻的流媒体与结果处理逻辑。现有测试覆盖较广，但内部职责耦合导致任何局部修改都触及大文件。

## Goals / Non-Goals

**Goals:**

- 将纯转换逻辑与 I/O 编排分离。
- 统一文件、RTSP 和 LVS 路径可共享的时间、证据和模型响应规范化。
- 保持所有公开入口和兼容返回行为。

**Non-Goals:**

- 不改变 `UnderstandingResult`、`EvidenceRef` 等共享模型。
- 不改变长视频阈值、帧选择策略、模型 prompt 或外部服务协议。
- 不以任意行数目标替代职责与测试边界。

## Decisions

1. 先提取无 I/O 的纯函数，包括时间值规范化、模型输出转 `UnderstandingResult`、事件/证据构造和 reasoning 分离。这些函数使用表驱动单元测试锁定行为。
2. 将帧获取/编码、VLM 调用、长视频分析和 RTSP/VST 解析保留为可注入的 I/O 边界，避免纯 helper 依赖 cv2、网络或全局配置。
3. `video_understanding.py` 保留公共 facade 和注册入口；内部实现可以移动到 `video_understanding_*` 模块，但原 import 路径继续工作。
4. LVS 路径只复用语义完全一致的 helper。存在 source type、sensor 或时间语义差异时，通过显式参数表达，不用条件堆叠隐藏差异。
5. 每次抽取一个职责并运行对应单元测试，最后再执行完整视频理解与验收测试。

## Risks / Trade-offs

- [风险] 拆分可能改变 monkeypatch 的目标路径。 -> 公共 facade 保留稳定别名，测试优先 patch 明确依赖注入点。
- [风险] 默认参数或 metadata 顺序在重构中漂移。 -> 对完整模型输出和兼容文本路径做快照式结构断言。
- [风险] 过度共享使 RTSP 与文件语义耦合。 -> 只共享纯转换核心，保留 source adapter。

## Migration Plan

1. 补充纯函数和兼容路径的 characterization tests。
2. 逐块提取纯转换与 I/O adapter，保持 facade 不变。
3. 迁移 LVS 可共享逻辑并运行路径矩阵测试。
4. 任一步出现行为差异时回滚该职责抽取，不叠加后续迁移。

## Open Questions

无。
