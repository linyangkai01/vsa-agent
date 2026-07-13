## 1. 配置、领域模型与持久层

- [x] 1.1 为 recorded-video、Worker、媒体工具、provider 和生产搜索增加配置模型、校验、环境变量解析及单元测试
- [x] 1.2 定义 Asset、UploadSession、Job、JobStep、Segment 的领域模型、状态迁移和错误码，并为非法迁移编写测试
- [ ] 1.3 实现 SQLite WAL schema、版本迁移和 repository 接口，覆盖原子任务领取、租约、心跳、检查点和并发测试
- [ ] 1.4 实现基于 UUID 路径的 LocalAssetStore、原子发布、配额/磁盘检查、临时块回收和路径安全测试

## 2. 原版 UI 上传与媒体兼容 API

- [ ] 2.1 实现 `POST /api/v1/videos` 上传会话 API、输入限制和同源 upload URL 返回契约
- [ ] 2.2 实现 nvstreamer 分块接收、块幂等校验、最终原子合并及 `sensorId/streamId` 兼容响应
- [ ] 2.3 实现 `POST /api/v1/videos/{asset_id}/complete` 的幂等任务创建，以及任务查询、重试和取消 API
- [ ] 2.4 实现原版 UI 所需的 VST facade 子集：视频列表、sensor 列表、storage size、缩略图和媒体 URL
- [ ] 2.5 实现支持 HTTP Range、时间 offset 和浏览器播放 proxy 的媒体响应，并覆盖 200/206/416、安全路径和取消请求测试
- [ ] 2.6 实现 `DELETE /api/v1/videos/{asset_id}` 的取消、软删除、ES/派生文件/源文件清理和重复删除幂等行为

## 3. 可替换录播分析流水线

- [x] 3.1 定义 Segmenter、VisionProvider、EmbeddingProvider、AssetStore 和 JobRepository 端口及测试替身
- [ ] 3.2 实现固定时间 Segmenter、稳定 segment ID、timeline origin/offset 转换及边界测试
- [ ] 3.3 实现 ffprobe 媒体探测、代表帧提取和按需 ffmpeg MP4 playback proxy，覆盖 MP4/MKV 和损坏媒体
- [ ] 3.4 实现 OpenAI-compatible 视觉描述 provider，包含结构化输出校验、超时、限流和安全日志
- [ ] 3.5 实现 OpenAI-compatible embedding provider，验证向量维度并禁止生产 profile 静默 mock 降级
- [ ] 3.6 实现 pipeline 编排、阶段 manifest/checksum、检查点复用、配置快照和可重复处理测试

## 4. Worker、恢复与生命周期

- [ ] 4.1 实现独立 Worker 入口、并发槽位、原子领取、租约续期、优雅停止和 heartbeat readiness
- [ ] 4.2 实现 retryable/permanent 错误分类、30 秒/2 分钟/10 分钟退避、最大尝试次数和最后错误持久化
- [ ] 4.3 实现 Worker 崩溃后租约回收、阶段恢复和不重复模型调用/ES 文档的故障注入测试
- [ ] 4.4 实现处理中取消、失败后显式重试、孤儿 chunk/临时产物回收及磁盘空间不足处理

## 5. Elasticsearch 生产索引与搜索

- [ ] 5.1 实现显式版本化 segment mapping、embedding 维度校验、index bootstrap 和 alias 管理
- [ ] 5.2 实现 manifest 到 segment 文档的确定性投影、bulk 写入、部分失败处理、对账和失败清理
- [ ] 5.3 调整真实 query embedding 和 ES 搜索，使生产 profile fail closed，测试/smoke fallback 必须显式启用
- [ ] 5.4 保持 `/api/v1/search` 原版 UI 返回契约，并验证 asset/segment identity、时间、缩略图和相似度字段

## 6. 原版 UI 最小调整

- [ ] 6.1 扩展上传完成响应类型以读取 job ID/status URL，同时保留既有三段式 chunk headers 和路径
- [ ] 6.2 在 Chat 和 Video Management 上传界面轮询任务状态，正确显示 processing、completed、failed 和 cancelled
- [ ] 6.3 扩展 Next 同源代理以流式转发 multipart chunk、任务 API、缩略图和 Range 媒体，不缓冲大文件
- [ ] 6.4 验证搜索结果缩略图、VST URL facade 和时间段播放，并保持未涉及的原版 UI 模块不变

## 7. 单脚本运行、doctor 与日志

- [ ] 7.1 将 runtime doctor 加入单一启动入口，检查 conda/Python、npm、Docker、ffprobe/ffmpeg、写权限、磁盘、模型和 ES mapping
- [ ] 7.2 扩展启动脚本管理 Worker PID/readiness/信号，且端口只回收当前用户拥有的监听进程
- [ ] 7.3 实现按 run ID 保存 stack/API/Worker/UI/ES/process manifest 日志、终端前缀汇聚、敏感字段脱敏和保留策略
- [ ] 7.4 将默认启动改为非写入 readiness，并实现使用隔离索引且自动清理的显式 `--validate` 模式
- [ ] 7.5 配置 UI 相对 `/api/v1` 和 `/api/v1/vst` 同源访问，验证单个 UI SSH 隧道覆盖完整业务流

## 8. 自动化验证与质量门槛

- [ ] 8.1 为上传、状态机、repository、Segmenter、provider、ES mapping、媒体 Range 和删除补齐单元测试
- [ ] 8.2 使用临时 SQLite/文件目录、真实 Elasticsearch 和假 OpenAI-compatible 服务运行组件集成测试
- [ ] 8.3 覆盖重复 chunk/complete、provider 429/5xx、ES bulk 部分失败、Worker 中断恢复和级联删除故障测试
- [ ] 8.4 使用 Playwright 验证原版 UI 上传 MP4/MKV、任务进度、搜索命中、缩略图和时间段播放
- [ ] 8.5 运行全量 Python/前端测试、lint、OpenSpec strict validate，并修复本 change 引入的失败或非条件 skip

## 9. 文档、服务器验证与收尾

- [ ] 9.1 更新中文运行手册、配置说明、故障诊断和 `docs/DEVELOPMENT_STATUS.md`
- [ ] 9.2 将代码同步到批准的 Ubuntu 项目环境，使用真实 OpenAI-compatible 配置验证三个并发视频和 Worker 重启恢复
- [ ] 9.3 记录不含密钥的服务器验收证据、搜索/HTTP 206/删除结果和日志路径
- [ ] 9.4 完成标准代码审查、Comet verify、分支合并、master 推送及 OpenSpec 归档
