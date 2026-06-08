# Batch 4 审查 — 视频工具 + API 层

> 审查日期: 2026-06-08
> vsa: `src/vsa_agent/` / NVIDIA: `_nvidia-original/agent/src/vss_agents/`
> 判定: ✅一致 / ⚠️简化有差距 / ❌缺失 / —框架差异不适用

---

## 1. tools/video_understanding.py

NVIDIA: 11 函数/类 | vsa: 3 函数/类

### 1.1 数据模型 — VideoUnderstandingInput

| 字段 | NVIDIA类型 | NVIDIA默认 | vsa类型 | vsa默认 | 判定 |
|------|-----------|-----------|---------|--------|------|
| `sensor_id` | `str` 必填 | — | `str` 必填 | — | ✅ |
| `start_timestamp` | `str` 必填 | — | `str` 必填 | — | ✅ |
| `end_timestamp` | `str` 必填 | — | `str` 必填 | — | ✅ |
| `user_prompt` | `str` 必填 | — | `str` 必填 | — | ✅ |
| `object_ids` | `list[str] \| None` | `None` | ❌ 缺失 | — | ⚠️ P2 |
| `vlm_reasoning` | `bool \| None` | `None` | ❌ 缺失 | — | ⚠️ P2 |
| `model_config` | `{"extra": "forbid"}` | — | ❌ | — | P3 |

> **判定: ⚠️ 4/7字段。** 核心字段(sensor_id/start/end/user_prompt)完全一致。
> - `object_ids`: 视频叠加显示对象框。前端功能，**P2**。
> - `vlm_reasoning`: 启用VLM推理模式。对接真实VLM时**P2**。
> - `model_config`: 极小的健壮性提升。**P3**。

### 1.2 数据模型 — VideoUnderstandingConfig

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `vlm_name` | `LLMRef` 必填 | ❌ | — P2 |
| `minio_url` | `str` `"http://localhost:9000"` | ❌ | — P2 |
| `access_key` | `str` `"minioadmin"` | ❌ | — P2 |
| `secret_key` | `str` `"minioadmin"` | ❌ | — P2 |
| `bucket_name` | `str` `"my-bucket"` | ❌ | — P2 |
| `max_frames` | `int` `24` | ❌ | — P2 |
| `max_fps` | `int` `2` | ❌ | — P2 |
| `min_pixels` | `int` `1568` | ❌ | — P2 |
| `max_pixels` | `int` `345600` | ❌ | — P2 |
| `reasoning` | `bool` `False` | ❌ | — P2 |
| `filter_thinking` | `bool` `False` | ❌ | — P2 |
| `use_vst` | `bool` `True` | ❌ | — P2 |
| `time_format` | `Literal["iso","offset"]` | ❌ | — P2 |
| `video_url_tool` | `str \| None` | ❌ | — P2 |
| `use_base64` | `bool` `False` | ❌ | — P2 |
| `system_prompt` | `str \| None` | ❌ | — P2 |
| `vlm_mode` | `str \| None` `"local"` | ❌ | — P2 |
| `internal_ip` | `str \| None` `""` | ❌ | — P2 |
| `external_ip` | `str \| None` `""` | ❌ | — P2 |
| `vst_internal_url` | `str \| None` | ❌ | — P2 |

> **判定: 全部20字段缺失。** 但这些是真实VLM基础设施配置(MinIO/VST/Cosmos)，vsa暂不需要。**全部P2。**

### 1.3 函数对比

| # | NVIDIA函数 | vsa函数 | 判定 | 必要性 |
|---|-----------|---------|------|--------|
| 1 | `_parse_thinking_from_content(content)` | `_parse_thinking_from_content(content)` | ✅ | 核心 |
| 2 | `VideoUnderstandingOffsetInput` | ❌ | — P2 | offset模式 |
| 3 | `validate_start_and_end_time(cls, info)` | ❌ | — P3 | 验证器 |
| 4 | `extend_timestamp(start_time, end_time)` | ❌ | — P2 | 时间扩展 |
| 5 | `_build_vlm_messages(...)` | ❌ | ⚠️ P1 | VLM消息构建 |
| 6 | `video_understanding(config, builder)` (NAT) | `video_understanding_tool(...)` (@register_tool) | ✅ | 核心 |
| 7 | `_video_understanding(video_understanding_input)` | (内联在video_understanding_tool中) | ⚠️ | 核心 |
| 8 | `_video_understanding_offset(...)` | ❌ | — P2 | offset模式 |
| 9 | `_video_understanding_iso(...)` | ❌ | ⚠️ | ISO模式 |

> **判定: ✅ 核心2函数实现。** 最大的P1差距是`_build_vlm_messages`——构建发送给VLM的消息体(含系统提示词/图片编码/用户查询)。当前vsa将其内联在工具函数中，**P1: 提取为独立函数以支持测试和复用。**

### 1.4 行为差异

| 行为 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| VLM调用 | `Builder.get_llm(vlm_name)` → async for chunks | `model_adapter.invoke(messages)` → 单次调用 | ⚠️ |
| 流式输出 | ✅ yield chunks | ❌ 单次返回 | P2 |
| thinking过滤 | ✅ `_parse_thinking_from_content` | ✅ 相同 | ✅ |
| 时间格式 | ISO + offset 双模式 | ISO only | P2 |
| 视频获取 | VST/MinIO URL构建 | 直接文件路径 | — 环境差异 |
| 帧编码 | base64 / URL | 文件路径 | — 环境差异 |

> **核心行为一致。** thinking解析完全匹配。差异主要是后端基础设施(VST/MinIO)和流式输出。

### video_understanding.py 小结

| 类别 | NVIDIA | vsa | 完成率 |
|------|--------|-----|--------|
| VideoUnderstandingInput | 7字段 | 5字段 | 71% |
| VideoUnderstandingConfig | 20字段 | 0 | 0% — P2 |
| 核心函数 | 4 | 2 | 50% |
| Config/工具注册 | 1 | 1 | ✅ |
| **评级** | | | **⚠️ 可用但简化** |

**P1 待办:**
```
[ ] _build_vlm_messages() 独立函数
```

**P2 待办 (大量VLM配置项):**
```
[ ] VideoUnderstandingConfig (20字段, 对接真实VLM时需要)
[ ] VideoUnderstandingOffsetInput + offset模式
[ ] extend_timestamp()
[ ] 流式VLM输出
[ ] VideoUnderstandingInput.object_ids + vlm_reasoning
```


## 2. tools/video_caption.py (NVIDIA only)

NVIDIA `video_caption.py` — 7 函数/类, 处理长视频分块+VLM描述。

vsa: 无独立文件, 功能合并到 `summary_agent.py`。

### 功能对应

| NVIDIA video_caption | vsa summary_agent | 判定 |
|---------------------|-------------------|------|
| `VideoCaptionInput` (filename/start/end/user_prompt/fps/duration) | `SummaryAgentInput` (query/video_path/chunk_duration/max_chunks) | ⚠️ 字段不同但语义对等 |
| `VideoCaptionConfig` (llm/prompt/retries/vss_url等) | — (通过函数参数注入) | — |
| `call_vlm_partition(...)` (分批调VLM) | (内联在execute_summary中) | ⚠️ |
| `video_caption()` (NAT注册) | `summary_agent_tool()` (@register_tool) | ✅ |
| `_video_caption_vss(...)` (VSS后端模式) | — | — P2 |
| `_video_caption(...)` (直接VLM模式) | `execute_summary()` | ⚠️ |

> **NVIDIA的video_caption和vsa的summary_agent功能对等**——都是长视频分块→帧提取→VLM→聚合。
> 差异: NVIDIA有VSS后端模式+重试+可配置prompt，vsa更简洁但功能等价。
> **判定: ✅ 功能对等，无需对齐。**


## 3. tools/frame_extract.py

vsa: `tools/frame_extract.py` (3 函数)  
NVIDIA: `utils/frame_select.py` (2 函数) — 没有独立注册为工具

### 函数对比

| NVIDIA | vsa | 判定 |
|--------|-----|------|
| `frame_select(video_path, start_timestamp, end_timestamp, step_size) -> list[str]` | `_extract_frames(cap, fps, total_frames, start_timestamp, end_timestamp, step_size) -> list[str]` | ⚠️ |
| `has_nvidia_gpu() -> bool` | ❌ 缺失 | — P3 |
| — | `frame_extract_tool(...)` (@register_tool) | vsa新增 |

**参数差异:**
- NVIDIA: `video_path` (每次调用打开视频)
- vsa: `cap` (已打开的cv2.VideoCapture对象) + `fps` + `total_frames` (避免重复open)

> **vsa的改进避免了重复打开视频**，是优化而非缺陷。
> `has_nvidia_gpu()` 缺失 — **P3**，仅影响硬件加速。

**判定: ✅ 功能对等。** 核心帧提取逻辑一致。vsa额外注册为工具方便Agent调用。


## 4. API 层

### 4.1 文件对照

| NVIDIA API 文件 | 函数数 | vsa API 文件 | 函数数 | 判定 |
|----------------|--------|-------------|--------|------|
| `health_endpoint.py` | 3 | `health.py` | 1 | ✅ |
| `custom_fastapi_worker.py` | 4 | `routes.py` | 4 | ⚠️ |
| `video_search_ingest.py` | 4 | `video_search_ingest.py` | 1 | ⚠️ |
| `video_upload_url.py` | 8 | `video_upload_url.py` | 1 | ⚠️ |
| `rtsp_stream_api.py` | 22 | ❌ | 0 | — P2 |
| `video_delete.py` | 7 | ❌ | 0 | — P2 |
| `register.py` | — | — | — | — |

### 4.2 详细对比

| 功能 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| 健康检查 | ✅ `/health` | ✅ `/health` | ✅ |
| Chat端点 | ✅ `/chat` (WebSocket+HTTP) | ✅ `POST /chat` + SSE stream | ✅ |
| 视频上传URL | ✅ MinIO presigned URL (带bucket/access_key) | ✅ 简化版 | ⚠️ |
| 视频搜索入库 | ✅ VST streaming ingest (带RTSP流管理) | ✅ 简化版 mock | ⚠️ |
| RTSP流管理 | ✅ 添加/删除/监控RTSP流 (22函数) | ❌ | — P2 |
| 视频删除 | ✅ ES删除 + RTVI清理 (7函数) | ❌ | — P2 |
| 路由注册 | ✅ `register_*_routes(app, config)` | ✅ FastAPI router | ✅ |

> **判定: ⚠️ 核心API (health/chat/upload/ingest) 全部实现但简化。**
> RTSP流管理和视频删除是NVIDIA的生产环境功能，vsa当前不需要。

### 4.3 routes.py 详细状态

| 端点 | 方法 | 功能 | 判定 |
|------|------|------|------|
| `/health` | GET | 健康检查 | ✅ |
| `/chat` | POST | ChatRequest → Agent → 流式响应 | ✅ |
| `/chat/stream` | GET | SSE事件流 | ✅ |
| (NVIDIA) WebSocket `/chat` | WS | 双向流式通信 | — P2 |

> **核心聊天功能完整。**


## 5. Batch 4 总结

### 判定矩阵

| 模块 | 评级 | 核心差距 |
|------|------|---------|
| video_understanding.py | ⚠️ 可用 | `_build_vlm_messages` P1, Config全缺失P2 |
| video_caption.py | — vsa无 | 功能合并到summary_agent ✅ |
| frame_extract.py | ✅ 对等 | `has_nvidia_gpu` P3 |
| API — health | ✅ | — |
| API — chat/routes | ✅ | — |
| API — upload/ingest | ⚠️ 简化 | 简化mock, 对接真实MinIO/VST时补齐 |
| API — rtsp/delete | — P2 | 暂不需要 |

### 所有待办

```
P1 (影响核心功能):
  [ ] _build_vlm_messages() 独立函数 (video_understanding)

P2 (后续优化 — VLM/API基础设施):
  [ ] VideoUnderstandingConfig (20字段)
  [ ] VideoUnderstandingOffsetInput + offset模式
  [ ] extend_timestamp()
  [ ] 流式VLM输出
  [ ] VideoUnderstandingInput.object_ids + vlm_reasoning
  [ ] RTSP stream API (22函数)
  [ ] Video delete API (7函数)
  [ ] WebSocket /chat
  [ ] 视频上传URL MinIO presigned

P3 (极低优先级):
  [ ] has_nvidia_gpu()
  [ ] VideoUnderstandingInput model_config forbid extra
  [ ] validate_start_and_end_time validator
```

### 关键发现

1. **视频工具层已经可用** — frame_extract 和 video_understanding 核心功能完整
2. **最大的P1差距只有1个**: `_build_vlm_messages` 提取为独立函数
3. **API层核心端点完整** — health/chat/upload/ingest 全部工作
4. **大量P2项是基础设施依赖** — MinIO/VST/RTSP, 对接真实后端时逐步补齐
5. **video_caption功能已由summary_agent替代** — 设计良好,无需额外工作
