## 1. Characterization 测试

- [x] 1.1 为字符串、字典和既有 `UnderstandingResult` 的规范化输出补充完整结构断言。
- [x] 1.2 为文件、RTSP、LVS、短视频、长视频、帧输入和旧文本返回建立路径矩阵。
- [x] 1.3 记录当前进度事件、artifact/trace、metadata 和异常降级行为，先让边界测试覆盖现状。

## 2. 提取纯转换边界

- [x] 2.1 提取时间规范化、reasoning 分离、事件与证据构造 helper，并通过无 I/O 单元测试。
- [x] 2.2 提取模型响应到 `UnderstandingResult` 的单一转换边界，保持所有默认字段和兼容行为。
- [x] 2.3 保留 `video_understanding.py` 的公共 import、工具注册和 monkeypatch 兼容 facade。

## 3. 拆分 I/O 编排

- [x] 3.1 保留现有帧获取/编码和 VLM 调用的显式可注入边界，不破坏 monkeypatch 路径。
- [x] 3.2 将短视频、长视频和 RTSP/VST source adapter 保留在 facade，与提取后的结果转换边界分离。
- [x] 3.3 迁移 LVS 路径复用语义一致的时间 helper，并显式保留 sensor、source type 和时间差异。

## 4. 验证与质量收尾

- [x] 4.1 运行视频理解、LVS、shared data model 和 acceptance 路径测试。
- [x] 4.2 运行 Ruff 门禁和全量 `pytest -q`，确认 facade 与注册入口未回归。
- [x] 4.3 更新 `docs/DEVELOPMENT_STATUS.md`，记录模块边界、保留的兼容路径和验证结果。

<!-- review skipped: multi-agent execution was not authorized for this run -->
