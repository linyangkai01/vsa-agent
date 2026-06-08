# vsa-agent Phase A-D 实现计划

> 日期: 2026-06-08
> 基准: [project-audit-complete.md](../reviews/project-audit-complete.md)
> 模式: TDD — 先写失败测试，再实现，验证通过，提交
> Python: `.conda-env/python.exe`
> 测试命令: `$env:PYTHONPATH="src"; python -m pytest <file> -v`

---

## 总体文件结构

```
src/vsa_agent/
├── agents/
│   ├── data_models.py          ★ 修改: AgentOutput.error_message
│   ├── search_agent.py         ★ 修改: SearchAgentInput 3字段
│   ├── summary_agent.py        (不改, Phase D 仅测试)
│   └── ...
├── model_adapter/
│   ├── base.py                 ★ 修改: 添加 max_retries 参数
│   └── openai_adapter.py       ★ 修改: 传入 max_retries
├── tools/
│   ├── search.py               ★★ 修改: 添加 6 个融合函数 + execute_core_search_wrapper
│   ├── attribute_search.py     ★ 修改: 添加 6 个 P1 函数
│   └── video_understanding.py  ★ 修改: 提取 _build_vlm_messages
└── utils/
    └── retry.py                ★ 新增: 重试装饰器

tests/
├── unit/
│   ├── test_phase_a_fusion_unit.py      ★ 新增: 融合函数单元测试
│   ├── test_phase_b_completion_unit.py  ★ 新增: 补齐函数单元测试
│   ├── test_phase_c_video_unit.py       ★ 新增: 视频函数单元测试
│   └── test_phase_d_long_video_unit.py  ★ 新增: 长视频单元测试
└── acceptance/
    ├── test_phase_a_search_e2e.py       ★ 新增: 搜索融合验收
    ├── test_phase_b_search_agent_e2e.py ★ 新增: Agent 搜索验收
    ├── test_phase_c_video_e2e.py        ★ 新增: 视频理解验收
    └── test_phase_d_long_video_e2e.py   ★ 新增: 长视频验收
```

---

## Phase A — 视频搜索·融合（P0: 6个融合函数）

**目标:** 实现 RRF + weighted_linear 融合算法，让 `search_tool()` 的 Path 3 从简单合并升级为真正的融合排序。

**涉及函数:**
- `_apply_weighted_linear_fusion()` — w_embed*embed + w_attribute*norm_attr
- `_apply_rrf_fusion()` — 1/(rank+k) + w*norm_attr
- `_apply_rrf_fusion_with_attribute_rank()` — 双 rank RRF
- `fusion_search_rerank()` — 编排三个融合方法
- `attribute_result_to_search_result()` — AttributeSearchResult → SearchResult
- `_run_attribute_only_search()` — 纯属性搜索编排

**涉及文件:**
- `src/vsa_agent/tools/search.py` — 添加 6 个函数，修改 `execute_core_search` 调用融合
- `tests/unit/test_phase_a_fusion_unit.py` — 12+ 个单元测试
- `tests/acceptance/test_phase_a_search_e2e.py` — 3 个验收测试

### Task A1: 创建单元测试文件

- [ ] 创建 `tests/unit/test_phase_a_fusion_unit.py`
- [ ] 写 import 和 helpers
- [ ] 写 `test_weighted_linear_single_video` — 单视频: 预期 fusion_score = 0.35*0.9 + 0.55*0.7 = 0.7
- [ ] 写 `test_weighted_linear_empty_list` — 空列表返回 []
- [ ] 写 `test_weighted_linear_custom_weights` — w_embed=0.5, w_attribute=0.3: 预期 0.5*0.8+0.3*0.6=0.58
- [ ] 写 `test_rrf_single_video` — 单视频: 预期 rrf_score = 1/(1+60) + 0.5*0.7 ≈ 0.366
- [ ] 写 `test_rrf_multi_video_ordering` — 2个视频: embed_score 高者 rank 低, 验证排序
- [ ] 写 `test_rrf_with_attribute_rank_two_videos` — 验证双 rank RRF 公式
- [ ] 写 `test_fusion_search_rerank_rrf` — 2个embed结果+属性, 验证调用链
- [ ] 写 `test_fusion_search_rerank_weighted_linear` — 同上, 切换融合方法
- [ ] 写 `test_fusion_search_rerank_unknown_method` — 未知融合方法抛 ValueError
- [ ] 写 `test_attribute_result_to_search_result` — 验证转换: video_name/similarity/sensor_id/object_ids
- [ ] 写 `test_attribute_result_to_search_result_frame_score` — frame_score>0 时取 frame_score
- [ ] 写 `test_run_attribute_only_search` — 验证返回 list[SearchResult]
- [ ] 运行: 确认 13 个 test FAIL (函数不存在)

### Task A2: 实现 `attribute_result_to_search_result()`

- [ ] 在 `search.py` 顶部添加 `from vsa_agent.tools.attribute_search import AttributeSearchResult`
- [ ] 实现函数: 接收 AttributeSearchResult/dict, 提取 metadata 字段, 构建 SearchResult
- [ ] `similarity` = frame_score if frame_score>0 else behavior_score
- [ ] `start_time` = metadata.start_time or metadata.frame_timestamp
- [ ] `end_time` = metadata.end_time or metadata.frame_timestamp
- [ ] `video_name` = video_name or metadata.video_name or metadata.sensor_id
- [ ] `object_ids` = [str(metadata.object_id)]
- [ ] 运行单元测试: test_attribute_result_to_search_result* 2个 pass

### Task A3: 实现 `_apply_weighted_linear_fusion()`

- [ ] 函数签名: `(video_data: list[dict], w_embed: float, w_attribute: float) -> list[SearchResult]`
- [ ] video_data 每个元素结构: `{"embed_result": SearchResult, "embed_score": float, "normalised_attribute_score": float, "screenshot_url": str, "object_ids": list[str]}`
- [ ] fusion_score = w_embed * embed_score + w_attribute * normalised_attribute_score
- [ ] 构建新 SearchResult(similarity=fusion_score, 其他字段从 embed_result 复制)
- [ ] 按 fusion_score 降序排序返回
- [ ] 运行单元测试: test_weighted_linear* 3个 pass

### Task A4: 实现 `_apply_rrf_fusion()`

- [ ] 函数签名: `(video_data: list[dict], rrf_k: int, rrf_w: float) -> list[SearchResult]`
- [ ] 按 embed_score 降序排序确定 rank (从1开始)
- [ ] rrf_score = 1.0 / (rank + rrf_k) + rrf_w * normalised_attribute_score
- [ ] 新 SearchResult(similarity=rrf_score, ...)
- [ ] 按 rrf_score 降序排序返回
- [ ] 运行单元测试: test_rrf* 2个 pass

### Task A5: 实现 `_apply_rrf_fusion_with_attribute_rank()`

- [ ] 函数签名: `(video_data: list[dict], rrf_k: int, rrf_w: float) -> list[SearchResult]`
- [ ] 按 embed_score 降序 → rank_embed
- [ ] 按 normalised_attribute_score 降序 → rank_attribute
- [ ] rrf_score = 1/(rank_embed + rrf_k) + rrf_w * (1/(rank_attribute + rrf_k))
- [ ] 注意: 用 `id(video)` 建立 rank 映射(因为 video_data 是 list of dict, dict 不能 hash, 用 id 做弱引用)
- [ ] 运行单元测试: test_rrf_with_attribute_rank* 1个 pass

### Task A6: 实现 `fusion_search_rerank()`

- [ ] 函数签名: `(embed_results: list[SearchResult], attributes: list[str], attribute_search_fn: Any, fusion_method: str = "rrf", rrf_k: int = 60, rrf_w: float = 0.5, w_attribute: float = 0.55, w_embed: float = 0.35, source_type: str = "video_file") -> list[SearchResult]`
- [ ] 对每个 embed_result, 调用 attribute_search_fn 获取属性结果
- [ ] 计算 normalised_attribute_score = sum(匹配分数) / len(attributes)
- [ ] 构建 video_data 列表
- [ ] 根据 fusion_method 调用对应融合函数
- [ ] unknown fusion_method → ValueError
- [ ] 运行单元测试: test_fusion_search_rerank* 3个 pass

### Task A7: 实现 `_run_attribute_only_search()`

- [ ] 函数签名: `(attributes: list[str], attribute_search_fn: Any, ...) -> list[SearchResult]`
- [ ] 调用 attribute_search_fn, 收集结果, 用 attribute_result_to_search_result 转换
- [ ] 按 similarity 降序排序, 截断 top_k
- [ ] 运行单元测试: test_run_attribute_only_search 1个 pass

### Task A8: 创建验收测试

- [ ] 创建 `tests/acceptance/` 目录
- [ ] 创建 `tests/acceptance/test_phase_a_search_e2e.py`
- [ ] 写 `test_rrf_fusion_e2e` — 构造 mock embed_store + attr_store, 调用 `search_tool()` 传入 decomposed_attributes + decomposed_has_action=True, 验证融合排序
- [ ] 写 `test_weighted_linear_fusion_e2e` — 同上, 验证 weighted_linear
- [ ] 写 `test_fusion_edge_case_no_attr_results` — 属性搜索返回空, 验证优雅降级
- [ ] 运行验收测试: 3个 pass

### Task A9: 集成 — 修改 `execute_core_search` Path 3

- [ ] 在 `execute_core_search` 的 Path 3 (has_action + has_attributes 分支), 将简单合并替换为 `fusion_search_rerank()` 调用
- [ ] 传入 `config.fusion_method` 等参数
- [ ] 运行 `test_integration_pipeline.py` 中 TestExecuteCoreSearchFull 的 2 个测试 — 确认不破坏

### Task A10: 合并 `Batch 1` P1: AgentOutput.error_message + model_adapter retry

- [ ] 在 `data_models.py` 的 `AgentOutput` 添加 `error_message: str | None = Field(default=None)`
- [ ] 在 `model_adapter/base.py` 的 `BaseModelAdapter` 添加 `max_retries: int = 1` init 参数
- [ ] 在 `model_adapter/openai_adapter.py` 传入 `max_retries=self.max_retries` 给 ChatOpenAI
- [ ] 写 2 个简单单元测试
- [ ] 运行全部 13 个融合单元 + 3 个验收 — 全部 pass

### Phase A 提交

- [ ] `git add` 所有改动
- [ ] `git commit -m "Phase A: fusion algorithms (RRF + weighted_linear) + model_adapter retry"`


## Phase B — 视频搜索·补齐（P1: SearchAgentInput + attribute_search 补齐）

**目标:** 补齐搜索链路的数据模型字段和属性搜索核心函数，使 SearchAgent 可以端到端运行。

**涉及函数:**
- `SearchAgentInput.use_attribute_search`, `source_type`, `use_critic`
- `SearchInput.min_cosine_similarity`, `use_critic`
- `execute_core_search_wrapper()`
- `search_single_attribute()`, `search_attributes()`, `_fuse_multi_attribute()`, `_append_multi_attribute()`, `_build_result()`

**涉及文件:**
- `src/vsa_agent/agents/search_agent.py` — SearchAgentInput 添加 3 字段
- `src/vsa_agent/tools/search.py` — SearchInput 添加 2 字段 + execute_core_search_wrapper
- `src/vsa_agent/tools/attribute_search.py` — 添加 5 个函数
- `tests/unit/test_phase_b_completion_unit.py`
- `tests/acceptance/test_phase_b_search_agent_e2e.py`

### Task B1: 创建单元测试文件

- [ ] 创建 `tests/unit/test_phase_b_completion_unit.py`
- [ ] 写 `test_search_agent_input_all_fields` — 验证 9 字段 (含 use_attribute_search/source_type/use_critic)
- [ ] 写 `test_search_input_all_fields` — 验证含 min_cosine_similarity/use_critic
- [ ] 写 `test_execute_core_search_wrapper` — mock generator, 验证返回 SearchOutput
- [ ] 写 `test_execute_core_search_wrapper_empty` — generator 无 SearchOutput, 返回空
- [ ] 写 `test_search_single_attribute` — 验证返回 list[AttributeSearchResult]
- [ ] 写 `test_search_attributes_multi_query` — 多个属性查询
- [ ] 写 `test_search_attributes_single_str` — 单字符串查询
- [ ] 写 `test_fuse_multi_attribute` — 验证融合逻辑
- [ ] 写 `test_append_multi_attribute` — 验证追加逻辑
- [ ] 写 `test_build_result` — 验证构建 SearchResult
- [ ] 运行: 确认 FAIL

### Task B2: 补齐 SearchAgentInput 3 字段

- [ ] 在 `SearchAgentInput` 添加 `use_attribute_search: bool | None = Field(default=None, ...)`
- [ ] 在 `SearchAgentInput` 添加 `source_type: Literal["video_file", "rtsp"] = Field(default="video_file", ...)`
- [ ] 在 `SearchAgentInput` 添加 `use_critic: bool = Field(default=True, ...)`
- [ ] 运行单元测试: test_search_agent_input_all_fields pass

### Task B3: 补齐 SearchInput 2 字段

- [ ] 在 `SearchInput` 添加 `min_cosine_similarity: float = Field(default=0.0, ...)`
- [ ] 在 `SearchInput` 添加 `use_critic: bool = Field(default=True, ...)`
- [ ] 运行单元测试: test_search_input_all_fields pass

### Task B4: 实现 `execute_core_search_wrapper()`

- [ ] 在 `search.py` 实现函数: 非流式包装, foreach execute_core_search, 遇到 SearchOutput 即返回
- [ ] 运行单元测试: test_execute_core_search_wrapper* 2个 pass

### Task B5: 实现 attribute_search 5 个 P1 函数

- [ ] `search_single_attribute(attribute: str, search_input=None) -> list[AttributeSearchResult]`
- [ ] `search_attributes(search_input: AttributeSearchInput) -> list[SearchResult]` — 遍历每个属性, 调用 search_single_attribute, 融合
- [ ] `_fuse_multi_attribute(attributes, attr_results_by_video) -> list[SearchResult]` — 取多个属性结果的交集/最佳
- [ ] `_append_multi_attribute(attributes, attr_results_by_video) -> list[SearchResult]` — 取并集
- [ ] `_build_result(metadata_dict, screenshot_url) -> SearchResult` — 从 metadata 构建 SearchResult
- [ ] 运行单元测试: 5 个 pass

### Task B6: 创建验收测试

- [ ] 创建 `tests/acceptance/test_phase_b_search_agent_e2e.py`
- [ ] 写 `test_search_agent_embed_only` — 用户输入无属性查询 → Path 2 embed-only
- [ ] 写 `test_search_agent_attribute_only` — 用户输入纯属性查询 → Path 1 attribute-only
- [ ] 写 `test_search_agent_fusion_with_critic` — 用户输入动作+属性 → Path 3 fusion + critic 验证
- [ ] 运行验收测试: 3个 pass

### Phase B 提交

- [ ] `git add` + `git commit -m "Phase B: SearchAgentInput/SearchInput fields + attribute_search functions + execute_core_search_wrapper"`


## Phase C — 视频理解（P1: _build_vlm_messages + 验收）

**目标:** 提取 `_build_vlm_messages` 为独立可测试函数，验证视频帧→VLM→结构化描述的完整链路。

**涉及函数:**
- `_build_vlm_messages(frames, query)` — 从 video_understanding_tool 中提取

**涉及文件:**
- `src/vsa_agent/tools/video_understanding.py` — 提取 _build_vlm_messages
- `tests/unit/test_phase_c_video_unit.py`
- `tests/acceptance/test_phase_c_video_e2e.py`

### Task C1: 创建单元测试

- [ ] 创建 `tests/unit/test_phase_c_video_unit.py`
- [ ] 写 `test_build_vlm_messages` — 传 frame 列表 + query, 验证返回 list[BaseMessage], 包含 system prompt
- [ ] 写 `test_build_vlm_messages_empty_frames` — 空帧列表不崩溃
- [ ] 写 `test_parse_thinking_no_tags` — 复用已有测试, 确认提取正确
- [ ] 写 `test_parse_thinking_with_thinking` — 同上
- [ ] 写 `test_frame_extract_with_mock_video` — mock cv2.VideoCapture, 验证返回 frames dict
- [ ] 运行: 确认至少 2 个 FAIL (_build_vlm_messages 不存在)

### Task C2: 提取 `_build_vlm_messages()`

- [ ] 在 `video_understanding.py` 中提取函数:
  ```
  def _build_vlm_messages(frames: list[str], query: str,
                          system_prompt: str | None = None) -> list[BaseMessage]
  ```
- [ ] 包含 system message(默认 prompt) + HumanMessage(frames + query)
- [ ] 修改 `video_understanding_tool` 调用此函数
- [ ] 运行单元测试: test_build_vlm_messages* 2个 pass
- [ ] 运行 `test_task18.py` 确认不破坏

### Task C3: 创建验收测试

- [ ] 创建 `tests/acceptance/test_phase_c_video_e2e.py`
- [ ] 写 `test_video_understanding_e2e` — 传入 frame 列表 + query, 调用 video_understanding_tool, 验证返回 structured 描述
- [ ] 写 `test_video_understanding_with_critic` — 先视频理解, 再用 critic_agent 验证结果
- [ ] 运行验收测试: 2个 pass

### Phase C 提交

- [ ] `git add` + `git commit -m "Phase C: _build_vlm_messages extraction + video understanding e2e test"`


## Phase D — 长视频理解（仅测试，代码已完成）

**目标:** 为已完成的 summary_agent 补充单元测试和验收测试，确认长视频分块→VLM→聚合报告链路稳健。

**涉及文件:**
- `tests/unit/test_phase_d_long_video_unit.py`
- `tests/acceptance/test_phase_d_long_video_e2e.py`

### Task D1: 创建单元测试

- [ ] 创建 `tests/unit/test_phase_d_long_video_unit.py`
- [ ] 写 `test_summary_zero_duration` — video_duration_sec=0, 验证返回 "0 seconds"
- [ ] 写 `test_summary_single_chunk` — 25s 视频, chunk=30s, 验证 1 个 chunk
- [ ] 写 `test_summary_multi_chunk` — 90s 视频, chunk=30s, 验证 3 个 chunk
- [ ] 写 `test_summary_chunk_truncation` — 1000s 视频, max_chunks=5, chunk=30s, 验证只处理 5 个
- [ ] 写 `test_summary_no_frames` — frame_extract 返回空, 验证 "No frames extracted"
- [ ] 写 `test_summary_input_model` — 验证 SummaryAgentInput 字段
- [ ] 运行: 6个 pass

### Task D2: 创建验收测试

- [ ] 创建 `tests/acceptance/test_phase_d_long_video_e2e.py`
- [ ] 写 `test_long_video_e2e` — mock frame_extract + VLM, 60s 视频, 验证报告含 "Video Summary Report"
- [ ] 写 `test_long_video_aggregation` — 3 chunks 各有不同内容, 验证聚合报告包含所有 chunk 的描述
- [ ] 运行验收测试: 2个 pass

### Phase D 提交

- [ ] `git add` + `git commit -m "Phase D: summary_agent unit + e2e tests"`

---

## 每个 Phase 完成后的验证清单

```
□ 该 Phase 的单元测试全部 pass
□ 该 Phase 的验收测试全部 pass
□ 项目级回归: 全部测试 (tests/unit + tests/acceptance) 无破坏
□ git commit
```

## 总测试数量预估

| Phase | 单元测试 | 验收测试 | 小计 |
|-------|---------|---------|------|
| A | 13 | 3 | 16 |
| B | 10 | 3 | 13 |
| C | 5 | 2 | 7 |
| D | 6 | 2 | 8 |
| **合计** | **34** | **10** | **44** |

加上已有测试 (~206), 全部完成后约 **250 个测试**。
