## ADDED Requirements

### Requirement: 视频理解公开契约保持
视频理解重构 MUST 保留现有工具入口、参数、结构化结果和兼容文本返回路径。

#### Scenario: 调用现有工具入口
- **WHEN** 调用者使用当前 `video_understanding` 或 LVS 入口处理支持的视频源
- **THEN** 返回类型、字段语义和错误类别 MUST 与重构前一致

### Requirement: 纯转换与 I/O 分离
模型输出、时间值和证据规范化 SHALL 通过不依赖网络、cv2 或全局配置的纯转换边界实现。

#### Scenario: 单元验证规范化
- **WHEN** 测试向规范化边界提供字符串、字典或既有 `UnderstandingResult`
- **THEN** 系统 MUST 生成与当前契约一致的结果且不执行外部 I/O

### Requirement: 视频源语义显式
文件视频、RTSP 和 LVS 路径 SHALL 显式保留各自的 source type、video path、sensor id 和时间范围语义。

#### Scenario: 构造不同来源证据
- **WHEN** 文件和 RTSP 路径处理等价的模型文本
- **THEN** 证据 MUST 分别包含合法的 `video_path` 或 `sensor_id`，且嵌套 source type 与结果一致

### Requirement: 重构由路径矩阵验证
视频理解职责抽取 MUST 由短视频、长视频、帧输入、RTSP 和旧文本返回测试覆盖。

#### Scenario: 完成内部模块拆分
- **WHEN** 任一职责从公共 facade 移出
- **THEN** 相关路径测试和全量 pytest MUST 在继续下一次抽取前通过
