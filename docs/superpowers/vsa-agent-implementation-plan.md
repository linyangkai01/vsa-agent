# VSA Agent 去 NVIDIA 依赖复现实施计划

> 目标: 按照 NVIDIA VSS 架构分模块复现，去除 NAT/Cosmos/VST 等 NVIDIA 依赖
> 日期: 2026-06-09
> 状态: 进行中

---

## 项目状态总览

### 已实现模块 (已完成)

| 模块 | 文件 | 状态 |
|------|------|------|
| 配置系统 | config.py, config.yaml | 完成 |
| 工具注册 | registry.py | 完成 |
| Agent 数据模型 | agents/data_models.py | 完成 |
| TopAgent (简化版) | agents/top_agent.py | 完成 |
| SearchAgent | agents/search_agent.py | 完成 |
| CriticAgent | agents/critic_agent.py | 完成 |
| 核心搜索 (数据模型+融合) | tools/search.py | 完成 |
| EmbedSearch (mock) | tools/embed_search.py | 完成 |
| AttributeSearch (mock) | tools/attribute_search.py | 完成 |
| VideoUnderstanding | tools/video_understanding.py | 完成 |
| 视频分析层 (nvschema/interface/query_builders) | video_analytics/ | 完成 |
| API 层 | api/ | 完成 |
| ModelAdapter | model_adapter/ | 完成 |
| MCP Server | mcp/ | 完成 |
| 测试框架 | tests/ | 完成 |

### 未实现模块 (Gap)

| 模块 | NVIDIA 文件 | 说明 | 优先级 |
|------|------------|------|--------|
| agents/report_agent.py | report_agent.py | 单事件报告 Agent | P2 |
| agents/multi_report_agent.py | multi_report_agent.py | 多事件报告 Agent | P2 |
| agents/postprocessing/ | postprocessing/ | 后处理管道 | P2 |
| tools/report_gen.py | report_gen.py | 报告生成工具 | P2 |
| tools/template_report_gen.py | template_report_gen.py | 模板报告生成 | P2 |
| tools/video_report_gen.py | video_report_gen.py | 视频报告生成 | P2 |
| tools/chart_generator.py | chart_generator.py | 图表生成 | P2 |
| tools/fov_counts_with_chart.py | fov_counts_with_chart.py | FOV 计数+图表 | P2 |
| tools/incidents.py | incidents.py | 事件管理 | P2 |
| tools/geolocation.py | geolocation.py | 地理位置 | P2 |
| tools/multi_incident_formatter.py | multi_incident_formatter.py | 多事件格式化 | P2 |
| tools/video_caption.py | video_caption.py | 视频字幕 | P2 |
| tools/video_detailed_caption.py | video_detailed_caption.py | 详细视频字幕 | P2 |
| tools/video_skim_caption.py | video_skim_caption.py | 视频快速字幕 | P2 |
| tools/video_frame_timestamp.py | video_frame_timestamp.py | 视频帧时间戳 | P2 |
| tools/lvs_video_understanding.py | lvs_video_understanding.py | 长视频理解 | P1 |
| tools/vss_summarize.py | vss_summarize.py | VSS 汇总 | P1 |
| tools/prompt_gen.py | prompt_gen.py | VLM prompt 生成 | P1 |
| embed/embed.py | embed.py | EmbedClient ABC | P1 |
| embed/cosmos_embed.py | cosmos_embed.py | Cosmos 嵌入客户端 | P1 |
| embed/rtvi_cv_embed.py | rtvi_cv_embed.py | RTVI CV 嵌入客户端 | P1 |
| data_models/vss.py | vss.py | MediaInfoOffset/Incident | P1 |
| utils/frame_select.py | frame_select.py | 帧选择 | P1 |
| utils/time_convert.py | time_convert.py | 时间转换 | P1 |
| utils/time_measure.py | time_measure.py | 时间测量 | P3 |
| utils/url_translation.py | url_translation.py | URL 翻译 | P1 |
| utils/reasoning_parsing.py | reasoning_parsing.py | 推理内容解析 | P1 |
| utils/reasoning_utils.py | reasoning_utils.py | 推理工具 | P1 |
| utils/markdown_parser.py | markdown_parser.py | Markdown 解析 | P3 |
| utils/parser.py | parser.py | 通用解析 | P3 |
| utils/video_file.py | video_file.py | 视频文件工具 | P3 |
| utils/asyncmixin.py | asyncmixin.py | 异步初始化 | P1 |
| api/rtsp_stream_api.py | rtsp_stream_api.py | RTSP 流管理 | P3 |
| api/video_delete.py | video_delete.py | 视频删除 | P3 |
| evaluators/ | evaluators/ | 评估框架 | P3 |
| prompt.py | prompt.py | 独立 prompt 常量 | P1 |

### 需要去 NVIDIA 化的依赖

| NVIDIA 依赖 | 替代方案 | 影响模块 |
|-------------|----------|----------|
| nat.* (NeMo Agent Toolkit) | 自建 registry + config | 所有 agents, tools |
| CosmosEmbedClient | OpenAI Embeddings API | embed_search |
| RTVICVEmbedClient | OpenAI Embeddings API | attribute_search |
| VST 服务 | 本地文件系统 / MinIO | video_understanding, tools/vst/ |
| boto3 (MinIO) | 保留（开源） | video_understanding |


---

## Phase 0 — 基础设施补齐 (P0)

**目标**: 补齐当前项目缺失的基础模块，使架构与 NVIDIA 对齐

### Task 0.1: 创建 prompt.py
- [ ] 从 NVIDIA prompt.py 移植所有 prompt 常量
- [ ] 从 config.yaml 的 prompts 段迁移到 prompt.py
- [ ] 更新 config.py 移除 prompts 段（或保留为覆盖）

### Task 0.2: 补齐 data_models/vss.py
- [ ] 实现 MediaInfoOffset 数据模型
- [ ] 实现 Incident 数据模型
- [ ] 实现 ParserMixin

### Task 0.3: 补齐 embed/ 层
- [ ] 实现 embed/embed.py (EmbedClient ABC)
- [ ] 实现 embed/cosmos_embed.py (OpenAI 替代 Cosmos)
- [ ] 实现 embed/rtvi_cv_embed.py (OpenAI 替代 RTVI CV)

### Task 0.4: 补齐 utils/ 工具函数
- [ ] 实现 utils/frame_select.py
- [ ] 实现 utils/time_convert.py
- [ ] 实现 utils/url_translation.py
- [ ] 实现 utils/reasoning_parsing.py
- [ ] 实现 utils/reasoning_utils.py
- [ ] 实现 utils/asyncmixin.py

### Task 0.5: 更新 TopAgent 对齐 NVIDIA
- [ ] 添加 plan-then-execute 模式
- [ ] 添加 postprocessing 管道支持
- [ ] 添加子 Agent 流式支持


---

## Phase 1 — 视频搜索增强 (P1)

**目标**: 将 mock 实现替换为真实实现，完善搜索链路

### Task 1.1: 实现 embed_search.py (真实 ES 查询)
- [x] 实现 _generate_query_embedding() 使用 OpenAI Embeddings
- [x] 实现 _build_es_query() 构建嵌套 KNN 查询
- [x] 实现 _process_search_hit() 处理 ES 结果
- [x] 实现 ES 分数转余弦相似度
- [x] 添加 SearchConfig 到 config.py
- [x] 安装 elasticsearch 依赖

### Task 1.2: 实现 attribute_search.py (真实 ES 查询)
- [x] 实现 search_single_attribute() 行为嵌入搜索
- [ ] 实现 _perform_frame_lookups() 帧级查找
- [ ] 实现 _fuse_multi_attribute() / _append_multi_attribute()
- [ ] 实现 _deduplicate_by_object()

### Task 1.3: 完善 search.py 融合算法
- [x] 实现置信度阈值检查 (embed_confidence_threshold)
- [x] 实现 Critic 验证循环
- [x] 实现 execute_core_search() 流式生成器
- [x] 添加 enable_critic / search_max_iterations 配置


---

## Phase 2 — 视频理解完善 (P1)

**目标**: 完善 video_understanding 工具

### Task 2.1: 完善 video_understanding.py
- [ ] 对齐 NVIDIA VideoUnderstandingConfig (max_fps, min_pixels, reasoning, filter_thinking)
- [ ] 支持 ISO 和 offset 两种时间格式
- [ ] 支持 VST/MinIO 两种视频源
- [ ] 实现 URL 翻译
- [ ] 实现 VLM 重试逻辑

### Task 2.2: 实现 lvs_video_understanding.py
- [ ] 长视频分块处理 (chunk_duration / num_frames_per_chunk)
- [ ] 场景/事件配置
- [ ] 结构化输出

### Task 2.3: 实现 vss_summarize.py
- [ ] Caption summarization
- [ ] 时间合并

### Task 2.4: 实现 prompt_gen.py
- [ ] 根据用户意图动态生成 VLM 子 prompt

---

## Phase 3 — 报告生成 (P2)

**目标**: 实现报告生成 Agent 和工具

### Task 3.1: 实现 report_agent.py
### Task 3.2: 实现 multi_report_agent.py
### Task 3.3: 实现 report_gen.py / template_report_gen.py / video_report_gen.py
### Task 3.4: 实现 chart_generator.py / fov_counts_with_chart.py

---

## Phase 4 — 剩余离线工具 (P2)

**目标**: 补齐 incidents, geo, captions 等工具

### Task 4.1-4.8: 实现 incidents.py / geolocation.py / video_caption.py 等

---

## Phase 5 — 在线视频 / RTSP / VST (P3)

**目标**: RTSP stream API, VST 服务集成, video_delete API

---

## 测试策略

| 层级 | 说明 |
|------|------|
| 单元测试 | 每个函数 1-3 个，细粒度 |
| 业务流验收 | 每个 Phase 2-3 个，验证完整链路 |

### 测试命令
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/unit/ tests/acceptance/ -v
```

---

## 验收标准

每个 Phase 完成后:
1. 该 Phase 的单元测试全部 pass
2. 该 Phase 的验收测试全部 pass
3. 项目级回归: 全部测试无破坏
4. git commit
