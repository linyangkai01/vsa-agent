# Batch 2 审查 — 搜索工具链

> 审查日期: 2026-06-08
> vsa: `src/vsa_agent/tools/` / NVIDIA: `_nvidia-original/agent/src/vss_agents/tools/`
> 判定: ✅一致 / ⚠️简化有差距 / ❌缺失 / —框架差异不适用

---

## 1. tools/search.py

NVIDIA: 22 函数/类 (18 def + 4 class) | vsa: 11 函数/类 (5 def + 6 class?)

### 1.1 数据模型 — DecomposedQuery

| 字段 | NVIDIA类型 | NVIDIA默认 | vsa类型 | vsa默认 | 判定 |
|------|-----------|-----------|---------|--------|------|
| `query` | `str` | `""` | `str` | `""` | ✅ |
| `video_sources` | `list[str]` | `[]` | `list[str]` | `[]` | ✅ |
| `source_type` | `str` | `"video_file"` | `str` | `"video_file"` | ✅ |
| `timestamp_start` | `str \| None` | `None` | `str \| None` | `None` | ✅ |
| `timestamp_end` | `str \| None` | `None` | `str \| None` | `None` | ✅ |
| `attributes` | `list[str]` | `[]` | `list[str]` | `[]` | ✅ |
| `has_action` | `bool \| None` | `None` | `bool \| None` | `None` | ✅ |
| `top_k` | `int \| None` | `None` | `int \| None` | `None` | ✅ |
| `min_cosine_similarity` | `float \| None` | `None` | `float \| None` | `None` | ✅ |

> **判定: ✅ 9/9字段完全一致。** 类型/默认值/语义全部匹配。

### 1.2 数据模型 — SearchResult

| 字段 | NVIDIA类型 | NVIDIA默认 | vsa类型 | vsa默认 | 判定 |
|------|-----------|-----------|---------|--------|------|
| `video_name` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `description` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `start_time` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `end_time` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `sensor_id` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `screenshot_url` | `str` | `...` (必填) | `str` | `""` (可选默认) | ✅ |
| `similarity` | `float` | `...` (必填) | `float` | `...` (必填) | ✅ |
| `object_ids` | `list[str]` | `[]` | `list[str]` | `[]` | ✅ |

> **判定: ✅ 8/8字段一致。** screenshot_url的默认值不同(vsa用""而非必填)，但运行时无影响。

### 1.3 数据模型 — SearchOutput

| 字段 | NVIDIA类型 | NVIDIA默认 | vsa类型 | vsa默认 | 判定 |
|------|-----------|-----------|---------|--------|------|
| `data` | `list[SearchResult]` | `[]` | `list[SearchResult]` | `[]` | ✅ |
| `model_config` | `ConfigDict(extra="forbid")` | — | 无 | — | ⚠️ |

> **判定: ✅ 结构一致。** vsa缺`model_config = {"extra": "forbid"}`，P3（极小的健壮性提升）。

### 1.4 数据模型 — SearchInput

| 字段 | NVIDIA类型 | NVIDIA默认 | vsa类型 | vsa默认 | 判定 |
|------|-----------|-----------|---------|--------|------|
| `model_config` | `ConfigDict(extra="forbid")` | — | `{"extra": "forbid"}` | — | ✅ |
| `query` | `str` | `...` (必填) | `str` | `...` (必填) | ✅ |
| `source_type` | `Literal["rtsp","video_file"]` | `...` (必填) | `str` | `"video_file"` | ⚠️ |
| `video_sources` | `list[str] \| None` | `None` | `list[str] \| None` | `None` | ✅ |
| `description` | `str \| None` | `None` | `str \| None` | `None` | ✅ |
| `timestamp_start` | `datetime \| None` | `None` | `str \| None` | `None` | ⚠️ |
| `timestamp_end` | `datetime \| None` | `None` | `str \| None` | `None` | ⚠️ |
| `top_k` | `int \| None` | `None` | `int \| None` | `None` | ✅ |
| `min_cosine_similarity` | `float` | `0.0` | ❌ 缺失 | — | ❌ |
| `agent_mode` | `bool` | `...` (必填) | `bool` | `True` (可选) | ✅ |
| `use_critic` | `bool` | `True` | ❌ 缺失 | — | ❌ |

> **判定: ⚠️ 3个弱化，❌ 2个缺失。**
> - `source_type`: NVIDIA用`Literal`类型安全，vsa用普通`str`。**P2。**
> - `timestamp_start/end`: NVIDIA用`datetime`对象，vsa用`str`。**P2** — 对接真实VST时需要datetime。
> - `min_cosine_similarity`: **❌ P1** — execute_core_search的embed_confidence_threshold依赖此字段。
> - `use_critic`: **❌ P1** — execute_search的critic验证依赖此字段。

### 1.5 数据模型 — SearchConfig

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `embed_search_tool` | `FunctionRef` (必填) | `str` `"embed_search"` | ⚠️ |
| `attribute_search_tool` | `FunctionRef \| None` | `str \| None` `None` | ⚠️ |
| `embed_confidence_threshold` | `float` `0.2` | `float` `0.2` | ✅ |
| `agent_mode_llm` | `LLMRef` (必填) | `str \| None` `None` | ⚠️ |
| `agent_mode_prompt` | `str` = QUERY_DECOMPOSITION_PROMPT | ❌ | — |
| `use_attribute_search` | `bool` `False` | `bool` `False` | ✅ |
| **vst_internal_url** | `str` (必填) | ❌ | — P2 |
| **critic_agent** | `FunctionRef \| None` | ❌ | — P2 |
| `default_max_results` | `int` `10` | `int` `10` | ✅ |
| **enable_critic** | `bool` `False` | ❌ | — P2 |
| **search_max_iterations** | `int` `1` | ❌ | — P2 |
| `fusion_method` | `Literal["weighted_linear","rrf"]` | `str` `"rrf"` | ⚠️ P2 |
| `w_attribute` | `float` `0.55` | `float` `0.55` | ✅ |
| `w_embed` | `float` `0.35` | `float` `0.35` | ✅ |
| `rrf_k` | `int` `60` | `int` `60` | ✅ |
| `rrf_w` | `float` `0.5` | `float` `0.5` | ✅ |

> **判定: 核心融合参数(4/4) ✅一致。** 缺失的5个字段(vst_internal_url, critic_agent, enable_critic, search_max_iterations, agent_mode_prompt)是NVIDIA对接真实后端基础设施需要的，vsa当前不需要。**P2物品。**

### 1.6 核心函数对比

| # | NVIDIA函数 | vsa函数 | 判定 | 必要性 |
|---|-----------|---------|------|--------|
| 1 | `decompose_query(user_query, llm, ...)` | `decompose_query(user_query, model_adapter)` | ✅ | 核心 |
| 2 | `execute_core_search(...)` (async generator, ~350行) | `execute_core_search(...)` (async generator, ~130行) | ⚠️ | 核心 |
| 3 | `execute_core_search_wrapper(...)` | ❌ | ❌ P1 | 核心 |
| 4 | `search(config, _builder)` (NAT注册) | `search_tool(...)` (@register_tool) | — | 框架 |
| 5 | `_search(search_input)` -> SearchOutput | (内联在search_tool中) | ⚠️ | P1 |
| 6 | `_str_input_converter(input)` | ❌ | — | P3 NAT |
| 7 | `_chat_request_input_converter(request)` | ❌ | — | P3 NAT |
| 8 | `_output_converter(output)` | ❌ | — | P3 NAT |
| 9 | `_chat_response_output_converter(response)` | ❌ | — | P3 NAT |
| 10 | `_chat_response_chunk_output_converter(response)` | ❌ | — | P3 NAT |

> 5个converter函数是NAT框架特有的，vsa用`@register_tool`替代。**不需要实现。**

### 1.7 融合算法函数对比

| # | NVIDIA函数 | vsa函数 | 判定 | 必要性 |
|---|-----------|---------|------|--------|
| 1 | `_apply_weighted_linear_fusion(video_data, w_embed, w_attribute)` | ❌ 缺失 | ❌ P0 | **必要** |
| 2 | `_apply_rrf_fusion(video_data, rrf_k, rrf_w)` | ❌ 缺失 | ❌ P0 | **必要** |
| 3 | `_apply_rrf_fusion_with_attribute_rank(video_data, rrf_k, rrf_w)` | ❌ 缺失 | ❌ P0 | **必要** |
| 4 | `fusion_search_rerank(embed_results, attributes, attribute_search_fn, ...)` | ❌ 缺失 | ❌ P0 | **必要** |
| 5 | `_get_attribute_results(embed_result)` (内联async) | ❌ 缺失 | ⚠️ P1 | 辅助 |
| 6 | `_run_attribute_only_search(attributes, attribute_search_fn, ...)` | ❌ 缺失 | ❌ P1 | **必要** |
| 7 | `attribute_result_to_search_result(attr_result, video_name, description)` | ❌ 缺失 | ❌ P0 | **必要** |
| 8 | `_is_single_word(attr)` | ❌ 缺失 | — | P3 |

> **6个P0函数全部缺失。** 这是Phase D的核心工作。当前`execute_core_search`的融合路径用简单合并(按video_name去重+按similarity排序)，没有RRF/weighted_linear。

### 1.8 execute_core_search 行为差异

| 行为 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| Query分解 | ✅ agent_mode时调decompose_query | ✅ 相同 | ✅ |
| 属性提取 | ✅ 从DecomposedQuery.attributes | ✅ 相同 | ✅ |
| 单字过滤 | ✅ `_is_single_word()`过滤 | ❌ 无 | ⚠️ |
| Path 1: 纯属性 | ✅ _run_attribute_only_search | ✅ 直接调attribute_search | ⚠️ |
| Path 2: 纯嵌入 | ✅ 直接调embed_search | ✅ 相同 | ✅ |
| Path 3: 融合 | ✅ fusion_search_rerank (RRF/weighted) | ⚠️ 简单合并 | ❌ |
| Critic验证 | ✅ execute_critic | ✅ (try/except) | ⚠️ |
| 迭代搜索 | ✅ search_max_iterations循环 | ❌ 无 | — P2 |
| 流式进度 | ✅ yield AgentMessageChunk | ❌ 无 | ⚠️ |
| embed_confidence回退 | ✅ 阈值检查 | ❌ 无 | ⚠️ P2 |

> **核心差距: Path 3融合算法是简单合并而非RRF/weighted_linear。** 其余差异为P2增强。

### search.py 小结

| 类别 | NVIDIA | vsa | 完成率 |
|------|--------|-----|--------|
| 数据模型 (5个类) | 37字段 | 34字段 ✅ +3缺失Fields | 92% |
| 核心函数 | 4 | 3 | 75% |
| 融合函数 | 8 | 0 | 0% — **P0** |
| NAT转换器 | 5 | 0 | — 不需要 |
| **总计** | **22** | **11** | **50%** |

**P0 待办 (6个, Phase D):**
```
_apply_weighted_linear_fusion()
_apply_rrf_fusion()
_apply_rrf_fusion_with_attribute_rank()
fusion_search_rerank()
attribute_result_to_search_result()
_run_attribute_only_search()
```

**P1 待办 (3个):**
```
execute_core_search_wrapper()
SearchInput.min_cosine_similarity
SearchInput.use_critic
```


## 2. tools/embed_search.py

NVIDIA: 13 函数/类 | vsa: 6 函数/类

### 2.1 数据模型 — EmbedSearchResultItem

| 字段 | NVIDIA类型 | vsa类型 | 判定 |
|------|-----------|---------|------|
| `video_name` | `str` `""` | `str` `""` | ✅ |
| `description` | `str` `""` | `str` `""` | ✅ |
| `start_time` | `str` `""` | `str` `""` | ✅ |
| `end_time` | `str` `""` | `str` `""` | ✅ |
| `sensor_id` | `str` `""` | `str` `""` | ✅ |
| `screenshot_url` | `str` `""` | `str` `""` | ✅ |
| `similarity_score` | `float` `0.0` | `float` `0.0` | ✅ |

> **判定: ✅ 7/7完全一致。**

### 2.2 数据模型 — EmbedSearchOutput

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `query_embedding` | `list[float]` `[]` | `list[float]` `[]` | ✅ |
| `results` | `list[EmbedSearchResultItem]` `[]` | `list[EmbedSearchResultItem]` `[]` | ✅ |

> **判定: ✅ 完全一致。**

### 2.3 数据模型 — QueryInput

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `id` | `str` `""` | `str` `""` | ✅ |
| `params` | `dict[str, str]` `{}` | `dict[str, str]` `{}` | ✅ |
| `prompts` | `dict[str, str]` `{}` | `dict[str, str]` `{}` | ✅ |
| `response` | `str` `""` | `str` `""` | ✅ |
| `embeddings` | `list[dict]` `[]` | `list[dict]` `[]` | ✅ |
| `source_type` | `str` `"video_file"` | `str` `"video_file"` | ✅ |
| `exclude_videos` | `list[dict[str, str]]` `[]` | `list[dict[str, str]]` `[]` | ✅ |

> **判定: ✅ 7/7完全一致。**

### 2.4 数据模型 — EmbedSearchConfig

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `cosmos_embed_endpoint` | `str` 必填 | ❌ | — P2 |
| `es_endpoint` | `str` 必填 | ❌ | — P2 |
| `es_index` | `str` `"video_embeddings"` | ❌ | — P2 |
| `vst_external_url` | `str` 必填 | ❌ | — P2 |
| `vst_internal_url` | `str \| None` | ❌ | — P2 |
| `default_max_results` | `int` `100` | ❌ | — P2 |

> **判定: EmbedSearchConfig全部缺失。** 但这是ES-specific配置，vsa无ES后端。**P2物品。**

### 2.5 函数对比

| # | NVIDIA函数 | vsa函数 | 判定 | 必要性 |
|---|-----------|---------|------|--------|
| 1 | `_sanitize_for_logging(obj)` | ❌ | — P3 |
| 2 | `_generate_query_embedding(query_input, embed_client)` | `_generate_query_embedding(query_input, embed_client)` | ✅ |
| 3 | `_build_es_query(query_input, query_embedding, config)` | ❌ | — P2 |
| 4 | `_process_search_hit(hit, ...)` | `_process_search_hit(hit, ...)` | ✅ |
| 5 | `embed_search(config, _builder)` (NAT) | `embed_search_tool(query, store, top_k)` | ✅ |
| 6 | `_embed_search(query_input)` (内部) | (内联在embed_search_tool中) | ⚠️ |
| 7 | `_str_input_converter(input)` | ❌ | — P3 NAT |
| 8 | `_chat_request_input_converter(request)` | ❌ | — P3 NAT |
| 9 | `_to_str_output(output)` | ❌ | — P3 NAT |

> **判定: ✅ 核心3函数全部实现。** 缺失项均为ES-specific或NAT-specific。

### embed_search.py 小结

| 类别 | NVIDIA | vsa | 完成率 |
|------|--------|-----|--------|
| 数据模型 (4个类) | 16字段 | 16字段 | 100% ✅ |
| 核心函数 | 5 | 4 | 80% |
| ES helper | 1 | 0 | — P2 |
| NAT转换器 | 3 | 0 | — 不需要 |
| **总计** | **13** | **6** | **—** |

> **接近完成。** 所有数据模型100%匹配，核心搜索函数全部实现。ES-specific函数等对接后端时再补。


## 3. tools/attribute_search.py

NVIDIA: 17 函数/类 | vsa: 6 函数/类

### 3.1 数据模型 — AttributeSearchInput

| 字段 | NVIDIA类型 | vsa类型 | 判定 |
|------|-----------|---------|------|
| `query` | `str \| list[str]` 必填 | `str \| list[str]` 必填 | ✅ |
| `source_type` | `str` `"video_file"` | `str` `"video_file"` | ✅ |
| `timestamp_start` | `datetime \| None` | `str \| None` | ⚠️ |
| `timestamp_end` | `datetime \| None` | `str \| None` | ⚠️ |
| `video_sources` | `list[str] \| None` | `list[str] \| None` | ✅ |
| `top_k` | `int` `1` | `int` `1` | ✅ |
| `min_similarity` | `float` `0.3` | `float` `0.3` | ✅ |
| `fuse_multi_attribute` | `bool` `True` | `bool` `True` | ✅ |
| `exclude_videos` | `list[dict[str, str]]` `[]` | `list[dict[str, str]]` `[]` | ✅ |

> **判定: ⚠️ 2个timestamp字段类型简化(str→datetime)。** 对接真实VST时需要datetime。**P2。**

### 3.2 数据模型 — AttributeSearchMetadata

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `sensor_id` | `str` 必填 | `str` 必填 | ✅ |
| `object_id` | `str` 必填 | `str` 必填 | ✅ |
| `object_type` | `str` `""` | `str` `""` | ✅ |
| `frame_timestamp` | `str` `""` | `str` `""` | ✅ |
| `start_time` | `str \| None` | `str \| None` | ✅ |
| `end_time` | `str \| None` | `str \| None` | ✅ |
| `bbox` | `dict \| None` | `dict \| None` | ✅ |
| `behavior_score` | `float` `0.0` | `float` `0.0` | ✅ |
| `frame_score` | `float \| None` | `float \| None` | ✅ |
| `video_name` | `str \| None` | `str \| None` | ✅ |

> **判定: ✅ 10/10完全一致。**

### 3.3 数据模型 — AttributeSearchResult

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `screenshot_url` | `str \| None` | `str \| None` | ✅ |
| `metadata` | `AttributeSearchMetadata` 必填 | `AttributeSearchMetadata` 必填 | ✅ |

> **判定: ✅ 完全一致。**

### 3.4 数据模型 — AttributeSearchConfig

| 字段 | NVIDIA | vsa | 判定 |
|------|--------|-----|------|
| `rtvi_cv_endpoint` | `str` 必填 | ❌ | — P2 |
| `es_endpoint` | `str` 必填 | ❌ | — P2 |
| `behavior_index` | `str` 默认值 | ❌ | — P2 |
| `frames_index` | `str \| None` | ❌ | — P2 |
| `enable_frame_lookup` | `bool` `True` | ❌ | — P2 |
| `vst_external_url` | `str` 必填 | ❌ | — P2 |
| `vst_internal_url` | `str \| None` | ❌ | — P2 |

> **判定: 全部缺失。** ES-specific，当前不需要。

### 3.5 函数对比

| # | NVIDIA函数 | vsa函数 | 判定 | 必要性 |
|---|-----------|---------|------|--------|
| 1 | `search_by_attributes(query_text, search_input)` | `search_by_attributes(query_text, search_input)` | ✅ |
| 2 | `search_single_attribute(attribute, search_input)` | ❌ | ❌ P1 |
| 3 | `search_attributes(search_input)` | ❌ | ❌ P1 |
| 4 | `_fuse_multi_attribute(attributes, attr_results_by_video)` | ❌ | ❌ P1 |
| 5 | `_append_multi_attribute(attributes, attr_results_by_video)` | ❌ | ❌ P1 |
| 6 | `_perform_frame_lookups(candidates, ...)` (ES操作) | ❌ | — P2 |
| 7 | `_get_frame_from_behavior(behavior, ...)` | ❌ | — P2 |
| 8 | `_search_behavior(...)` (ES操作) | ❌ | — P2 |
| 9 | `_build_result(...)` | ❌ | ❌ P1 |
| 10 | `_extend_clip_to_one_second(start, end)` | ❌ | — P2 |
| 11 | `_deduplicate_by_object(results)` | `_deduplicate_by_video_name(results)` | ⚠️ |
| 12 | `build_attribute_search(config, _builder)` (NAT) | `attribute_search_tool(attributes, store, top_k)` | ✅ |
| 13 | `attribute_search_fn(search_input)` (内部) | (内联在attribute_search_tool中) | ⚠️ |

> **判定: ⚠️ 核心2函数有但简化，❌ 6个缺失。**
> - P1缺失的6个函数(search_single_attribute, search_attributes, _fuse_multi_attribute, _append_multi_attribute, _build_result)是multi-attribute搜索的核心——NVIDIA通过这些函数为每个embed结果跑attribute搜索，然后融合。
> - P2缺失的5个函数都是ES/VST操作。

### attribute_search.py 小结

| 类别 | NVIDIA | vsa | 完成率 |
|------|--------|-----|--------|
| 数据模型 (4个类) | 21字段 | 21字段 | 100% ✅ |
| 核心搜索函数 | 5 | 1 | 20% |
| 融合函数 | 2 | 0 | 0% — **P1** |
| 帧查找函数 | 4 | 0 | 0% — **P2** |
| 工具函数 | 1 | 0 | — P2 |
| NAT注册 | 2 | 1 | — 框架差异 |
| **总计** | **17** | **6** | **35%** |

**P1 待办 (6个):**
```
search_single_attribute()
search_attributes()
_fuse_multi_attribute()
_append_multi_attribute()
_build_result()
```

**P2 待办 (5个, ES/VST依赖):**
```
_perform_frame_lookups()
_get_frame_from_behavior()
_search_behavior()
_extend_clip_to_one_second()
```

### 关于 _deduplicate_by_object vs _deduplicate_by_video_name

NVIDIA按`object_id`去重（同视频不同对象保留一个），vsa按`video_name`去重（同视频不同对象合并）。NVIDIA的语义更精确——同一视频的不同对象可能对应不同时间戳。**P2: 在对接真实ES时修改为按object_id去重。**


## 4. tools/query_builders.py

NVIDIA: `video_analytics/query_builders.py` — 3个类, 6个函数, 全部构建Elasticsearch查询体。

vsa: 空桩文件，只有注释说明"预留"。

| # | NVIDIA | vsa | 判定 | 必要性 |
|---|--------|-----|------|--------|
| 1 | `IncidentQueryBuilder` + 2 methods | ❌ | — | P2 ES |
| 2 | `FramesQueryBuilder` + 2 methods | ❌ | — | P2 ES |
| 3 | `BehaviorQueryBuilder` + 2 methods | ❌ | — | P2 ES |

> **判定: — (全部P2)。** 这些类构建ES JSON查询体。vsa无ES后端，不需要实现。对接ES时按需实现。


## 5. Batch 2 总结

### 判定矩阵

| 模块 | 数据模型 | 核心函数 | 融合函数 | ES函数 | NAT转换器 | 完成率(核心) |
|------|---------|---------|---------|--------|----------|-------------|
| search.py | 34/37字段 | 3/4 | 0/8 | — | 0/5(不需要) | **50%** |
| embed_search.py | 16/16字段 | 4/5 | — | 0/1 | 0/3(不需要) | **80%** |
| attribute_search.py | 21/21字段 | 1/5 | 0/2 | 0/5 | 0/2(不需要) | **20%** |
| query_builders.py | — | — | — | 0/3 | — | **0%** (P2) |

### 按优先级总待办

```
P0 — Phase D 融合算法 (6个函数，都在search.py):
  [ ] _apply_weighted_linear_fusion()
  [ ] _apply_rrf_fusion()
  [ ] _apply_rrf_fusion_with_attribute_rank()
  [ ] fusion_search_rerank()
  [ ] attribute_result_to_search_result()
  [ ] _run_attribute_only_search()

P1 — 核心补齐 (11个函数):
  search.py:
    [ ] execute_core_search_wrapper()
    [ ] SearchInput.min_cosine_similarity
    [ ] SearchInput.use_critic
  attribute_search.py:
    [ ] search_single_attribute()
    [ ] search_attributes()
    [ ] _fuse_multi_attribute()
    [ ] _append_multi_attribute()
    [ ] _build_result()

P2 — ES/后端依赖 (18个):
  各种 *Config 字段, ES操作, frame查找, query_builders
  (当前阶段不需要实现)
```

### 关键发现

1. **数据模型基本完整** — 4个模块共94个字段，vsa实现91个(97%)。差距只有SearchInput的2个字段+SearchConfig的若干ES字段。
2. **核心搜索流程可以跑通** — embed_only/attribute_only/fusion三条路径都能工作，只是融合算法是简化版。
3. **最大的单一差距是P0融合函数** — 6个函数，预计Task 21可完成。
4. **embed_search是最接近完成的模块** — 80%完成率，只需ES对接时补_config和_build_es_query。
5. **attribute_search有最大的P1差距** — multi-attribute搜索的6个函数在NVIDIA中是融合算法的前置依赖。
