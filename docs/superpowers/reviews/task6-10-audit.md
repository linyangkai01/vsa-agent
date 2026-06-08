# Task 6-10 模块完成率跟踪

> 对比基准: NVIDIA original (_nvidia-original/agent/src/vss_agents/)
> 标记: [x] 已完成 / [ ] 待实现 / [~] 简化实现

---

## tools/frame_extract.py (Task 8) — vs NVIDIA utils/frame_select.py

**NVIDIA: 2 函数 | vsa: 2 函数 | 字段: 函数参数一致**

| # | NVIDIA | vsa-agent | 状态 |
|---|--------|-----------|------|
| 1 | `frame_select(video_path,start,end,step_size)` -> list[str] | `_extract_frames(cap,fps,total_frames,...)` -> list[str] | [~] 参数不同:接受cap对象而非path |
| 2 | `has_nvidia_gpu()` -> bool | -- | [ ] ❌ 缺失 |
| -- | -- | `frame_extract_tool()` (注册) | vsa新增包装函数 |

**NVIDIA frame_select 参数:** video_path, start_timestamp, end_timestamp, step_size  
**vsa _extract_frames 参数:** cap, fps, total_frames, start_timestamp, end_timestamp, step_size

vsa 多传了 fps/total_frames 避免重复打开视频(review修复),是改进而非bug。

---

## tools/video_understanding.py (Task 9) — vs NVIDIA tools/video_understanding.py + video_caption.py

### vs video_understanding.py

**NVIDIA: 7 类/函数 | vsa: 1 函数**

| # | NVIDIA | vsa-agent | 状态 |
|---|--------|-----------|------|
| 1 | `_parse_thinking_from_content()` | -- | [ ] ❌ 缺失 |
| 2 | `class VideoUnderstandingConfig` (15+ field) | -- | [ ] ❌ 无配置模型 |
| 3 | `class VideoUnderstandingInput` | -- | [ ] ❌ 用简单参数 |
| 4 | `class VideoUnderstandingOffsetInput` | -- | [ ] ❌ |
| 5 | `extend_timestamp()` | -- | [ ] ❌ |
| 6 | `_build_vlm_messages()` | -- | [ ] ❌ (简化内联) |
| 7 | `video_understanding()` (NAT注册) | `video_understanding_tool()` | [~] 简化为单次VLM调用 |

### vs video_caption.py

**NVIDIA: 4 类/函数 | vsa: 0 (合并到 video_understanding)**

| # | NVIDIA | vsa-agent | 状态 |
|---|--------|-----------|------|
| 1 | `class VideoCaptionConfig` | -- | [ ] ❌ |
| 2 | `class VideoCaptionInput` | -- | [ ] ❌ |
| 3 | `call_vlm_partition()` (分批调VLM) | -- | [ ] ❌ |
| 4 | `video_caption()` (NAT注册) | -- | [ ] ❌ |
| -- | VSS backend 模式 | -- | [ ] ❌ |
| -- | max_retries + 错误重试 | -- | [ ] ❌ |
| -- | VST download 支持 | -- | [ ] ❌ |

---

## tools/echo_tool.py — vsa 独占, 无 NVIDIA 对应

| # | 函数 | 状态 | 备注 |
|---|------|------|------|
| 1 | `echo_tool()` | -- | vsa 测试用,无需审计 |

---

## tools/vector_store.py — vsa 独占, NVIDIA 用 ES

| # | 类 | 状态 | 备注 |
|---|------|------|------|
| 1 | `InMemoryVectorStore` | [ ] ❌ | 空实现,待替换为ES |
| 2 | `get_default_embed_store()` | [ ] ❌ | |
| 3 | `get_default_attr_store()` | [ ] ❌ | |
| 4 | `get_default_store()` | [ ] ❌ | |

---

## 数据模型字段对比

### VideoUnderstandingInput — 0/6 字段匹配(NVIDIA Pydantic → vsa keyword args)

| 字段 | NVIDIA | vsa | 备注 |
|------|--------|-----|------|
| sensor_id | ✅ | ❌ | vsa用frame_extract结果路径 |
| start_timestamp | ✅ | ❌ | vsa用max_frames参数 |
| end_timestamp | ✅ | ❌ | |
| user_prompt | ✅ | query参数 | [~] 改名 |
| object_ids | ✅ | ❌ | |
| vlm_reasoning | ✅ | ❌ | |

### VideoUnderstandingConfig — 0/13 字段匹配

NVIDIA有: vlm_name, minio_url, access_key, secret_key, bucket_name, max_frames, max_fps, min_pixels, max_pixels, reasoning, filter_thinking, use_vst, time_format, video_url_tool, use_base64, system_prompt, vlm_mode

vsa: DEFAULT_MAX_FRAMES=24 (硬编码)

---

## 总览 — Task 6-10 (未审计部分)

| 模块 | NVIDIA总数 | vsa已实现 | 完成率 | 备注 |
|------|----------|----------|--------|------|
| tools/frame_extract.py | 2 | 1 | 50% | 缺has_nvidia_gpu,函数签名有改进 |
| tools/video_understanding.py | 7 | 1 | 14% | 合并了video_caption功能 |
| tools/video_caption.py | 4 | 0 | 0% | 合并进video_understanding |
| tools/echo_tool.py | -- | -- | N/A | vsa独占 |
| tools/vector_store.py | -- | 0 | 0% | ES替代品 |
| **Task 8-9 整体** | **13** | **2** | **15%** | |

---

## 全部模块汇总

| 审计文档 | 范围 | 完成率 |
|----------|------|--------|
| [task0-5-audit.md](task0-5-audit.md) | 注册/模型/Agent/API/MCP | 14/19 = 74% |
| [search-module-audit.md](search-module-audit.md) | 搜索工具链 | 18/61 = 30% |
| 本文档 | 视频帧/理解/存储 | 2/13 = 15% |
| **合计** | **全项目** | **34/93 = 37%** |

> 上次更新: 2026-06-08
