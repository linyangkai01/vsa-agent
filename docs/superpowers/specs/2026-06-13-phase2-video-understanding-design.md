# Phase 2 视频理解设计

> 范围：`video_understanding.py`、`lvs_video_understanding.py`、`vss_summarize.py`、`prompt_gen.py`
> 日期：2026-06-13
> 目标：完成 Phase 2 的能力完整设计，并采用结构化 + 文本双轨输出

## 总体说明

Phase 2 的核心目标是：把视频理解统一到一套内部结构化结果上，再从这套结构化结果派生出对人类友好的文本总结。

整体设计继续保留 NVIDIA 原版的模块职责拆分：
- `prompt_gen.py`：负责生成面向 VLM 的观察 prompt
- `video_understanding.py`：负责分析单个短视频或单个分块
- `lvs_video_understanding.py`：负责长视频切块、调度和合并
- `vss_summarize.py`：负责生成最终总结输出

和原版相比，这里的核心升级是输出契约：
- 内部处理一律以结构化结果为主
- 面向用户的文本输出从结构化结果派生

这样做的直接收益是：后续 `report_agent`、图表、API 返回、评估模块都可以复用同一套结果对象。

## 业务流

短视频路径：
1. 用户查询先进入 `prompt_gen`
2. `prompt_gen` 生成当前意图下的观察 prompt
3. `video_understanding` 提取帧并调用 VLM
4. 将模型输出归一化为结构化 observations 和 events
5. `vss_summarize` 生成最终双轨输出

长视频路径：
1. 用户查询先进入 `prompt_gen`
2. `prompt_gen` 为整次长视频分析生成统一 prompt
3. `lvs_video_understanding` 对视频进行切块
4. 每个 chunk 调用 `video_understanding`
5. 将多个 chunk 的结果合并为统一结构化结果
6. `vss_summarize` 生成最终双轨输出

## 输出契约

Phase 2 使用一套共享的内部模型。

```python
class EvidenceRef(BaseModel):
    source_type: Literal["video_file", "rtsp"]
    video_path: str | None = None
    sensor_id: str | None = None
    frame_indices: list[int] = Field(default_factory=list)
    frame_timestamps: list[str] = Field(default_factory=list)
    start_timestamp: str | None = None
    end_timestamp: str | None = None


class ObservationChunk(BaseModel):
    chunk_id: str
    start_timestamp: str
    end_timestamp: str
    prompt_used: str
    raw_model_output: str
    normalized_text: str
    thinking: str | None = None
    confidence: float | None = None
    evidence: EvidenceRef


class DetectedEvent(BaseModel):
    event_id: str
    label: str
    description: str
    start_timestamp: str
    end_timestamp: str
    actors: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    location_hint: str | None = None
    severity: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class UnderstandingResult(BaseModel):
    query: str
    source_type: Literal["video_file", "rtsp"]
    summary_text: str
    chunks: list[ObservationChunk] = Field(default_factory=list)
    events: list[DetectedEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummaryResult(BaseModel):
    query: str
    text_output: str
    structured_output: UnderstandingResult
    metadata: dict[str, Any] = Field(default_factory=dict)
```

规则：
- `video_understanding` 和 `lvs_video_understanding` 都必须返回 `UnderstandingResult`
- 只有 `vss_summarize` 返回 `SummaryResult`
- 下游模块消费的是 `structured_output`，不是原始文本

## 模块职责

### `prompt_gen.py`

职责：
- 把用户意图翻译成适合 VLM 的观察 prompt

接口：

```python
async def generate_understanding_prompt(
    query: str,
    intent: str | None = None,
    context: dict[str, Any] | None = None,
) -> str
```

约束：
- 不做帧提取
- 不做模型调用
- 不做总结聚合

### `video_understanding.py`

职责：
- 分析一个短视频或一个有边界的时间段

接口：

```python
async def analyze_video_segment(
    video_path: str | None = None,
    frames: list[str] | None = None,
    query: str = "",
    source_type: str = "video_file",
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
    model_adapter=None,
    config: VideoUnderstandingConfig | None = None,
) -> UnderstandingResult
```

必须具备的能力：
- 支持 `offset` 和 `iso` 两种时间输入
- 将输出时间统一归一化到一种标准格式
- 对非本地视频源使用 `url_translation`
- 模型调用必须带有重试逻辑
- 是否保留 thinking 文本由配置控制

### `lvs_video_understanding.py`

职责：
- 负责长视频的切块分析编排

接口：

```python
async def analyze_long_video(
    video_path: str,
    query: str,
    source_type: str = "video_file",
    chunk_duration_sec: int = 30,
    max_frames_per_chunk: int = 12,
    model_adapter=None,
    config: LVSVideoUnderstandingConfig | None = None,
) -> UnderstandingResult
```

必须具备的能力：
- 按 chunk duration 切块
- 每个 chunk 调用 `video_understanding.analyze_video_segment`
- 按时间顺序合并 chunk
- 当标签和证据兼容时，合并相邻或重叠事件

### `vss_summarize.py`

职责：
- 从结构化理解结果生成最终双轨输出

接口：

```python
async def summarize_understanding_result(
    result: UnderstandingResult,
    query: str,
    model_adapter=None,
) -> SummaryResult
```

必须具备的能力：
- 生成简洁的人类可读输出
- 保留完整结构化结果
- 合并冗余或相邻 observations
- 在 model adapter 被 mock 时保持足够稳定，便于测试

## 配置设计

`VideoUnderstandingConfig` 作为短视频分析的基础配置，建议包含：
- `max_fps`
- `min_pixels`
- `max_pixels`
- `reasoning_effort`
- `filter_thinking`
- `max_retries`
- `time_format`: `iso | offset`
- `source_mode`: `local | translated`

`LVSVideoUnderstandingConfig` 额外增加：
- `chunk_duration_sec`
- `max_frames_per_chunk`
- `max_chunks`
- `merge_adjacent_events`

## 错误处理

规则：
- 单个 chunk 的帧提取失败，应让该 chunk 明确失败，不能静默吞掉
- 长视频编排如果配置允许，可以容忍部分 chunk 失败后继续
- 模型调用失败必须经过有限重试
- 时间戳解析失败必须抛出明确校验错误，不能猜测
- 无法解析或无法访问的 translated URL，必须在模型调用前失败

降级策略：
- 不能通过生成伪造内容来掩盖真实失败
- 只有在分析确实没有观察结果时，才允许返回空结果

## 测试策略

单元测试：
- data model construction and serialization
- prompt generation by intent
- timestamp normalization from `offset` and `iso`
- retry behavior
- thinking filtering
- chunk splitting and merge behavior
- summary generation with mocked adapters

验收测试：
- short video path: `prompt_gen -> video_understanding -> vss_summarize`
- long video path: `prompt_gen -> lvs_video_understanding -> vss_summarize`
- failure path: transient model error recovered by retry
- dual-track output path: `text_output` and `structured_output` both present and internally consistent

## 实现顺序

1. add shared understanding models
2. implement `prompt_gen.py`
3. refactor `video_understanding.py` to return `UnderstandingResult`
4. implement `lvs_video_understanding.py`
5. implement `vss_summarize.py`
6. add Phase 2 acceptance tests

## 验收标准

Phase 2 完成的标准：
- short-video and long-video paths both end in `SummaryResult`
- all internal module boundaries use the shared structured models
- `video_understanding` supports `iso` and `offset`
- model calls use retry logic
- text output is derived from structured output, not vice versa
- unit and acceptance tests pass without weakening existing Phase 1 coverage
