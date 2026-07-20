# 录播视频生产环境验收记录

状态：等待 Task 24 在批准的 Ubuntu 环境执行真实 provider 验收。本文件当前只定义证据落点，不声明服务器链路通过；运行 `scripts/recorded-video-validate.py` 后将由工具原子覆盖为本次结果。

## runtime

待采集：run ID、非敏感配置摘要、API/Worker/UI/Elasticsearch readiness 与日志路径。

## job_stages

待采集：并发样例任务、完整 checkpoint 顺序、attempt/耗时和中断恢复轨迹。

## provider

待采集：真实 VLM/embedding 模型标识、调用结果和安全日志检查。

## es

待采集：隔离/生产 alias、indexing/publish checkpoint、确定性文档与重复检查。

## search

待采集：查询、asset identity、时间段 identity、相似度和缩略图结果。

## media

待采集：缩略图内容、Range 状态、`Accept-Ranges` 与 `Content-Range`。

## delete

待采集：Elasticsearch、派生文件、源文件、SQLite 记录和重复操作结果。
