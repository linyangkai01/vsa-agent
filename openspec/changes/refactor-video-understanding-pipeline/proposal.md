## Why

视频理解主实现约 731 行，LVS 变体约 441 行，模型输出规范化、时间窗口处理、证据构造、产物记录和异常降级分散在多个分支中。重复编排增加了维护成本，也让行为差异只能依赖大量边界测试才能发现。

## What Changes

- 按职责拆分视频输入、模型输出规范化、证据构造、长视频路由和产物记录逻辑。
- 合并可共享的规范化、时间处理和错误处理实现。
- 保留现有 `video_understanding`、LVS 工具入口、返回类型、兼容文本路径和配置语义。
- 为拆分后的边界补充针对性单元测试，降低后续修改的回归范围。

## Capabilities

### New Capabilities

- `video-understanding-maintainability`: 为视频文件与 RTSP 理解路径提供清晰、可测试的内部职责边界。

### Modified Capabilities

无。此 change 只重构实现，不改变理解结果契约。

## Impact

- 影响 `src/vsa_agent/tools/video_understanding.py`、`lvs_video_understanding.py`、相关工具辅助模块及测试。
- 需要覆盖长视频、RTSP、本地帧路径、模型生成别名、证据类型和旧文本返回路径。
- 不改变公共工具签名、共享数据模型、API schema 或外部服务协议。
