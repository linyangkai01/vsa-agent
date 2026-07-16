# Task 21 后端集成与故障注入报告

## 结果

- 状态：完成（显式本地投影 fallback 模式）。
- 生产修复提交：`1fee515 fix: persist assembled video integrity`。
- 集成测试提交：见本报告所属提交。
- 测试范围：真实 FastAPI 路由、临时 SQLite、临时 data root、真实 OpenAI-compatible HTTP client、本地 `pytest-httpserver`、生产 pipeline、生产 Worker、租约/重试/删除状态机。

## TDD 证据

### RED

1. `pytest tests/integration/test_recorded_video_flow.py -q`
   - 结果：ERROR，`fixture 'recorded_video_stack' not found`，证明集成运行时尚未实现。
2. `pytest tests/unit/api/test_recorded_video_upload.py::test_final_chunk_persists_assembled_integrity_before_idempotent_complete -q`
   - 结果：FAIL，最后 chunk、重复 chunk 和 complete 的 HTTP 状态正确，但数据库实际为 `(size_bytes, sha256)=(0, '')`。
3. `pytest tests/unit/recorded_video/test_repository.py::test_finalize_assembled_source_is_atomic_and_integrity_idempotent -q`
   - 结果：FAIL，`JobRepository` 缺少 `finalize_assembled_source`。

### 根因与修复

上传创建 `Asset` 时使用未完成哨兵值 `size_bytes=0, sha256=''`，文件组装后只返回路径，没有持久化实际完整性；pipeline 随后校验源 SHA，导致真实 HTTP 上传必然以 `CORRUPT_MEDIA` 失败。

修复增加仓储事务：仅在所有 chunk 已确认且确认字节数匹配时持久化实际 size/SHA-256；相同摘要重复 finalize 幂等，不同摘要拒绝。API 在 source 成功组装后流式计算实际完整性并调用该事务，失败不会伪造 finalized 状态。

### GREEN

- integrity 定向测试：`2 passed`。
- integrity 相关完整回归：`80 passed`。
- integration fallback：`10 passed`。
- 最终合并验证：`90 passed, 1 warning in 25.74s`。
- Ruff：`All checks passed!`

## 故障覆盖

- 三个 MP4/MKV 并发上传：每个确定性 segment ID 恰好一个投影文档。
- 重复最后 chunk 与重复 complete：源字节、job 和文档均不重复。
- provider 429、503：进入 `retry_wait`，保留 error/attempt，第二次 attempt 完成。
- ES bulk 部分失败：attempt 投影回滚，重试后无重复文档。
- Worker 丢失：租约过期后 reclaim，attempt 从 1 递增至 2。
- 磁盘不足：HTTP 507，无 job、ES 文档或临时文件。
- 坏媒体：终态 failed，attempt=1，保留原始源文件且不发布文档。
- 取消：运行中 job 在租约回收后完成 cancel cleanup，不删除诊断源文件。
- 删除中断：首次 projection 删除失败返回 500；重复删除从检查点恢复，清除 ES、文件、job/upload/segment 并保留 deleted tombstone。

## 环境前提

- 真实 ES：设置 `VSA_TEST_ES_URL`，fixture 会 ping、创建唯一 alias/index，并在 teardown 删除。
- 显式 fallback：设置 `VSA_RECORDED_VIDEO_TEST_FALLBACK=1`。
- 两者均未设置时 fixture 直接 `pytest.fail`，不会 skip 或报告假通过。
- 测试不访问外网；provider 只监听本机临时端口。

本机没有 Docker、Elasticsearch、ffmpeg/ffprobe，因此本次 GREEN 使用显式 projection fallback 和可控媒体边界。真实 ES 分支已实现但本机未执行；真实 ffmpeg 媒体工具链不属于本次通过证据。

## 自审

- 未修改 Task 23 的 validator/docs/sync 文件，也未纳入其他代理的工作树变更。
- fallback 不是全 mock：API、SQLite、文件系统、provider HTTP 协议、pipeline、Worker 与状态机均为生产实现；仅 ES 和媒体外部进程边界可控替换。
- 每个故障测试同时检查 job 状态/attempt、投影文档和关键残留文件。
- 已验证未配置依赖模式明确失败；真实 ES 模式仍需在具备 ES 的验证环境执行。
