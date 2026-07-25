# 录播视频生产运行验证报告

- 总体结果：PASS

## runtime

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- acceptance_id: b9932665-3f18-4d16-ba09-da0877e40653
- launcher_runs: df73b078-9ff7-4db9-8f8b-aaa1fa092788,0a0387d8-be6e-4562-88b4-44042f271c42
- log_ref: /data/project/lyk/vsa-agent/.runtime/es-stack/runs/0a0387d8-be6e-4562-88b4-44042f271c42/stack.log
- secret_scan: PASS (无密钥)
无密钥配置摘要、两次 launcher run 与运行日志路径已记录。

## job_stages

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- concurrency: 3
- worker_restart: PASS
- asset_ids: 33b1864c-09f0-4c64-800b-1c4be6dc71dd,a88ee57d-668a-4ae9-a4e0-090f5056f817,7d45c9e1-268a-4203-9f76-66b29a3d8753
- job_ids: aa5edc5d-d135-43e4-9880-ac1c5d48c17e,61e0c59c-08d6-49cd-8cc8-8c33e89f86f2,1d90004a-fada-42bb-b038-b2aee50bc94d
- stage_history: 三并发任务已完成，Worker 重启后复用了已完成 checkpoint。

## provider

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- embedding_provider: openai_compatible
- embedding_model: text-embedding-v4
真实 provider 模型身份与 checkpoint 结果已逐项核对。

## es

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- endpoint: http://127.0.0.1:9200
- index: vsa-recorded-video-production-final-20260724-01
- document_count: 9
- expected_segment_count: 9
- dedup_count: 9
- segment_ids: 0e19168d-05a7-5075-ab0b-775e3979b30a,2c160e1e-a787-5936-8f83-b7511612cf98,71a9ff96-c5dc-57a5-aa88-05d5ceaa57f4,7707a728-1f44-5be3-bd57-8dfd413fe861,a841d4d2-5128-5378-bfbf-01680369c96e,d8f57419-c973-5f8b-89c6-9044c458f671,ede12d02-312b-526a-87d4-bc27c7d230a1,fa4c4a0b-5e7b-5750-9c1e-a2e2a1a4ea18,fcce26df-b53d-5449-8367-965c98e5d70b
Elasticsearch 文档与 SQLite deterministic segment identity 完全一致。

## search

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- similarity: 0.513
- result_asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- result_job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- result_segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- case_evidence_ref: /data/project/lyk/vsa-agent/docs/recorded-video-validation.cases.json
三个查询均通过原版 UI 同源代理绑定到各自 asset/job/segment。

## media

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- HTTP 206: PASS
- Accept-Ranges: bytes
- Content-Range: bytes 0-0/27664613
- validated_assets: 3
三个缩略图与 HTTP 206 Range 结果均已验证。

## qa

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- understood_assets: 3
- answer_excerpt: <intermediatestep>{"id":"vsa-agent-step-0","status":"in_progress","error":"","type":"system_intermediate","parent_id":"vsa-agent","intermediate_parent_id":"vsa-agent","content":{"name":"Thought","payload":"Analyzing user request (LLM iteration 1; 20 tools available)."},"time_stamp":"default","index"
- case_evidence_ref: /data/project/lyk/vsa-agent/docs/recorded-video-validation.cases.json
三个搜索结果均通过原版 UI `+ Chat` 等价上下文进入选中片段理解问答，并记录 video_understanding trace。

## delete

PASS
- run_id: 0a0387d8-be6e-4562-88b4-44042f271c42
- timestamp_utc: 2026-07-24T07:31:37.458570Z
- asset_id: 33b1864c-09f0-4c64-800b-1c4be6dc71dd
- job_id: aa5edc5d-d135-43e4-9880-ac1c5d48c17e
- segment_id: 2c160e1e-a787-5936-8f83-b7511612cf98
- provider: openai_compatible
- model: qwen3-vl-flash-2025-10-15
- cleanup_path: /data/project/lyk/vsa-validation-data/final-20260724-01/assets/33b1864c-09f0-4c64-800b-1c4be6dc71dd
- cleanup_status: PASS
- deleted_assets: 3
三个资产均完成双重幂等删除清理，ES、SQLite、媒体和文件路径无残留。
