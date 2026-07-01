# vsa-agent 与 NVIDIA VSS 原版综合审查 - 2026-07-01

## 1. 审查目的

本文件用于作为 `vsa-agent` 下一阶段开发的基准文档。审查目标不是判断当前项目是否逐文件复刻 NVIDIA VSS，而是回答一个更关键的问题：

> 当前 `vsa-agent` 是否正在朝着“去 NVIDIA 依赖、保留原版 VSS 业务价值、形成自己的开放视频智能 Agent”的方向推进？如果还没有完成，下一阶段应该补哪些业务链路？

项目最终目标已经在 `CONFIG.md` 中明确：保留视频搜索、视频理解、长视频处理、安全问答、报告生成、可回放日志与配置驱动能力，同时去掉 NVIDIA NIM、NeMo Agent Toolkit、VST/VIOS 必需运行时、Cosmos/RTVI 必需服务、NVIDIA Docker/Helm/Brev 部署栈等锁定。

## 2. 审查范围与证据

本次审查对照以下代码和文档：

| 类型 | 路径 | 用途 |
| --- | --- | --- |
| 当前项目 | `D:\WorkPlace\vsa-agent` | 当前自研 `vsa-agent` 实现 |
| 原版项目 | `D:\WorkPlace\video-search-and-summarization-main` | NVIDIA VSS Blueprint 原始参考 |
| 当前目标文档 | `CONFIG.md` | 当前项目目标、架构、配置原则 |
| 当前状态文档 | `docs/superpowers/reviews/project-status-2026-06-30.md` | 近期开发状态和验证记录 |
| 旧 gap 文档 | `docs/superpowers/reviews/nvidia-vss-gap-review-2026-06-30.md` | 初版原版对照审查 |
| 路线图 | `docs/superpowers/plans/2026-06-30-vss-business-flow-parity-roadmap.md` | 下一阶段业务流对齐路线 |
| OpenSpec 状态 | `openspec list --json` | 当前活跃变更状态 |
| 当前配置 | `config.yaml` | 统一配置和运行 profile |
| 原版 README | `D:\WorkPlace\video-search-and-summarization-main\README.md` | 原版总体业务架构 |
| 原版 Agent README | `D:\WorkPlace\video-search-and-summarization-main\services\agent\README.md` | 原版 agent 配置和运行方式 |

代码规模对照：

| 项目 | Agent 源码 Python 文件 | 测试 Python 文件 | 说明 |
| --- | ---: | ---: | --- |
| 当前 `vsa-agent` | 100 | 107 | 已经形成独立 package、测试体系和运行脚本 |
| 原版 `vss_agents` | 128 | 149 | 包含更多 NVIDIA 编排、VST、RAG、实时流、评估和部署相关代码 |

## 3. 一句话结论

当前项目已经完成了“自研开放版 VSA Agent”的核心骨架：统一配置、模型适配、LangGraph TopAgent、视频理解、长视频分块、QA、报告、搜索模块、可回放 trace、真实 DashScope API 验证和真实视频运行脚本都已经具备。

但当前还不能宣称完整替代原版 NVIDIA VSS。准确状态是：

- 已经替代了原版的 recorded-video 基础链路的大部分技术底座。
- 已经验证过 shared 模式真实视频长视频理解、QA、报告和日志产物。
- graph 模式已经具备 TopAgent 自主工具调用证据，但还需要持续稳定验证和减少重复 VLM 调用。
- 搜索模块结构已经存在，但“真实本地视频归档检索”还没有形成端到端验收。
- 原版实时流、NVIDIA 部署编排、Enterprise RAG、VST 工具全集、RTVI alert 等高级模块目前未移植，且其中很多应当是有意推迟，而不是当前阶段缺陷。

## 4. 当前项目已经完成的部分

### 4.1 配置工程化

当前项目已经从多份实验配置收敛到单一业务配置：

- `config.yaml` 是唯一提交的业务运行配置。
- `config.local.yaml` 用于本地敏感信息和机器差异，已加入 git ignore。
- `VSA_PROFILE` 用于切换 profile，例如 `dashscope_remote`、`hybrid_dashscope_llm_local_vlm`、`test`。
- `backends` 抽象 provider endpoint、base URL、API key env、是否需要 key。
- `profiles` 按角色绑定 `llm`、`vlm`、可扩展 `embedding`。
- `runtime` 管理 conda 环境、视频路径、trace 目录、默认 QA query。
- shell、yaml、markdown 已通过 `.gitattributes` 约束 LF，解决 Windows 到 Ubuntu 拷贝后的 CRLF 问题。

对原版的变化：

- 原版通过 `general`、`functions`、`llms`、`workflow` 和多套 developer profile `.env/config.yml` 管理运行。
- 当前项目没有照搬原版配置层级，而是压缩成更适合当前开发验证的 `backends/profiles/runtime/tools/prompts`。
- 当前配置更简单，更适合“远程百炼 API 测试”和未来“远程 LLM + 本地 vLLM/VLM”混合部署。

当前状态评估：基本完成，剩余是 metrics 字段和后续 profile 扩展。

### 4.2 模型适配层

当前项目已经具备：

- OpenAI-compatible adapter，可接 DashScope/Bailian 兼容接口。
- vLLM adapter，为后续本地模型服务保留接入点。
- LLM/VLM 分角色解析，避免把文本模型和视觉模型混在一起。
- live trace 中记录 model invoke request/response，便于检查实际调用模型。

对原版的变化：

- 原版主要围绕 NVIDIA NIM、NAT/AIQ Toolkit、NVIDIA 模型 profile。
- 当前项目用 `ModelAdapter` 替代 NVIDIA-specific runtime binding。
- 当前阶段以 DashScope 远程 API 跑实验，符合用户当前策略。

当前状态评估：可用。下一阶段需要补调用耗时、token、错误类型和费用估算类 metrics。

### 4.3 Agent 编排

当前项目已经有：

- `top_agent.py`：基于 LangGraph 的顶层 agent。
- `search_agent.py`：搜索 agent，含 query decomposition、embed/attribute/fusion、critic hooks。
- `critic_agent.py`：对搜索结果做 VLM critic 的结构保留。
- `report_agent.py`、`multi_report_agent.py`：报告生成路径。
- postprocessing validators：非空、安全 checklist、URL 检查等。
- registry：工具注册和发现机制。

对原版的变化：

- 原版 Agent 建在 NVIDIA AIQ/NAT 配置体系上，通过 `workflow` 选择 function/tool。
- 当前项目用更轻量的 LangGraph + registry 方式重建。
- 当前 TopAgent 工具列表做过限制，避免 LLM 直接调用低层 `video_report_gen` 等不适合暴露的工具。

当前状态评估：核心骨架完成，但 graph 模式还需要作为正式验收项稳定下来。

### 4.4 视频理解与长视频处理

当前项目已经有：

- `video_understanding.py`：本地视频文件分析入口。
- `lvs_video_understanding.py`：长视频分块理解。
- OpenCV 帧抽取和帧缓存能力。
- `LONG_VIDEO_THRESHOLD_SEC = 40`，长视频触发分块。
- `lvs_video_understanding.chunk_duration_sec: 30`。
- `lvs_video_understanding.max_frames_per_chunk: 8`。
- trace 中记录长视频分块和 VLM 调用事件。

对原版的变化：

- 原版 LVS 依赖更完整的 NVIDIA profile、LVS 服务路径、HITL/stream state 等。
- 当前项目保留“长视频分块 + 逐段 VLM + 汇总”这个业务本质，去掉 NVIDIA LVS 服务依赖。

当前状态评估：baseline 可用。下一阶段需要性能指标、分块预算控制、重复调用抑制和真实长视频多轮验收。

### 4.5 真实视频 live acceptance

当前项目已经有：

- `scripts/run_live_top_agent_video_dashscope.sh`。
- `src/vsa_agent/live_video_acceptance.py`。
- shared 模式：一次 video understanding 结果复用于 QA 和 report，成本更稳。
- graph 模式：TopAgent 自主选择工具，验证 agentic 行为。
- 输出目录：`artifacts/live-video-runs/<run_id>/`。
- 输出内容：`manifest.json`、`trace.jsonl`、`qa-final.txt`、`report-final.txt`、`frames/`、`tool-results/`。

已经观察到的运行事实：

- shared 模式已验证真实 Ubuntu 视频路径、DashScope profile、长视频分块、QA 和报告输出。
- graph 模式已经出现 `top_agent.agent.request`、`top_agent.agent.response`、`top_agent.tool.call`、`top_agent.tool.result`、`top_agent.final` 这类证据。
- 之前 graph 模式暴露过 `video_report_gen` 低层工具调用错误和重复 `video_understanding` 的问题，近期已做了 validator 和 prompt/tool 暴露策略上的修复。

当前状态评估：live runner 是项目目前最关键的价值闭环。shared 模式偏稳定验收，graph 模式偏 agent 自主性验收。

### 4.6 日志与可回放观测

当前项目已经有：

- `observability/live_trace.py`。
- JSONL trace 输出。
- model invoke request/response 记录。
- TopAgent tool call/result/final 记录。
- video understanding、long-video chunk、report agent、search agent trace。
- `live_run_validator.py` 可对 run directory 做自动检查。

对原版的变化：

- 原版有 Phoenix/telemetry 等更重的观测栈。
- 当前项目选择轻量 JSONL + artifacts，适合当前调试、复盘和用户手工检查。

当前状态评估：方向正确。缺少耗时、token、成本、chunk 级摘要等可运营指标。

### 4.7 搜索与视频归档能力

当前项目已经有：

- `search.py`。
- `embed_search.py`。
- `attribute_search.py`。
- `vector_store.py`。
- `video_db.py`。
- `find_video_tool.py`。
- `search_agent.py`。
- `critic_agent.py`。
- `SearchOutput`、`SearchResult`、incident 转换等结构。

对原版的变化：

- 原版搜索链路和 Cosmos/RTVI/Elasticsearch/knowledge retrieval 更深度耦合。
- 当前项目已经重建搜索 agent 和工具结构，但真实归档检索验收还不充分。

当前状态评估：模块存在，不等于业务闭环完成。下一阶段必须补“本地视频入库、自然语言搜索、返回时间段/视频名/相似度、可选 critic 验证”的端到端测试。

### 4.8 API 与服务层

当前项目已经有：

- FastAPI health/routes。
- rtsp stream api。
- video delete。
- video search ingest。
- video upload url。
- MCP server。

对原版的变化：

- 原版有 custom FastAPI worker、front-end config、video ingest、RTSP ingest/delete、更完整的服务和 UI profile。
- 当前项目有服务层雏形，但开发重心明显在离线视频 agent 验证，不在生产 API 完整复刻。

当前状态评估：够开发验证，不够宣称服务层 parity。

### 4.9 测试体系

当前项目已经有：

- 107 个 Python 测试文件。
- unit tests 覆盖 config、model adapter、agent、tools、api、observability、live runner、validator。
- acceptance tests 覆盖业务流、report、search、critic、video understanding、live API 等。
- 近期关键验证曾达到 selected tests 全绿，例如 graph fixes 后相关 18 个测试通过。

对原版的变化：

- 原版测试更多，尤其是 NVIDIA VST、orchestrator、knowledge retrieval、evaluator、RTVI alert、code executor 等部分。
- 当前项目测试更聚焦自研业务链路和去 NVIDIA 依赖后的运行方式。

当前状态评估：测试基础已成形，下一阶段要把 live run validator 作为强制 gate。

## 5. 与原版业务流逐项对照

| 原版 VSS 业务流 | 原版核心行为 | 当前项目状态 | 差异判断 |
| --- | --- | --- | --- |
| Q&A and Report Generation | 找到视频、VLM 分析、回答问题、生成报告 | 已有 shared 和 graph 两种 live runner；QA/report 输出已落盘 | 基本完成 baseline，但 graph 模式需稳定验收 |
| Long Video Summarization | 长视频切片、密集 caption、聚合总结 | 已有长视频分块和汇总路径 | 已替代核心思路，但缺性能/成本指标和更细的事件聚合质量 |
| Video Search | 自然语言检索视频归档，embedding/attribute/fusion | 模块存在，agent 存在，测试存在 | 还缺真实本地归档端到端验收 |
| Alert Verification | 用视频证据验证告警，降低误报 | critic/search/report 结构可支持部分验证 | 原版告警输入、实时 metadata 和行为分析未移植 |
| Real-Time Alerts | 持续流式 VLM 异常检测 | 未作为当前阶段目标 | 有意推迟，不应混入当前 recorded-video milestone |
| RAG Report | 用外部知识/策略 grounding 报告 | 未完整移植 | 有意推迟，报告质量稳定后再考虑 |
| VST/VIOS video ops | sensor、snapshot、timeline、clip、video list | 仅有轻量 VST client/find video 思路 | 未完整移植，且不应成为必需 runtime |
| NVIDIA deployment profiles | Docker Compose/Helm/Brev/NIM profile | 未移植，当前用 conda + config.yaml + script | 符合去 NVIDIA 依赖目标 |
| MCP tool surface | 通过 MCP 暴露视频分析工具 | 当前有 MCP server 雏形 | 需要后续验收是否真正可用 |

## 6. 当前项目对原版做了哪些修改或替换

| 原版部分 | 当前替换 | 目的 |
| --- | --- | --- |
| NVIDIA NIM/NAT/AIQ Toolkit 运行方式 | LangChain/LangGraph + ModelAdapter | 去掉 NVIDIA agent runtime 锁定 |
| 多 developer profile config.yml + .env | 单一 `config.yaml` + ignored `config.local.yaml` | 降低配置复杂度，支持实验和部署切换 |
| NVIDIA LLM/VLM profile | OpenAI-compatible + vLLM backend | 支持百炼远程 API 和未来本地模型 |
| 原版 LVS 服务链路 | 本地长视频分块 + VLM 调用 + 汇总 | 保留业务行为，去掉服务依赖 |
| VST 作为核心视频源 | 本地视频路径优先，VST 作为 optional integration | 先跑通 recorded-video 业务 |
| 原版 Phoenix/服务观测 | JSONL trace + artifacts + validator | 便于本地/Ubuntu 实验复盘 |
| 原版 report/search/evaluator 深层实现 | 自研简化版 agent/tools/evaluator | 先构造可控 baseline，再逐步补齐 |
| 原版部署栈 | conda env `vsa-agent` + shell runner | 适合当前 RTX 4090 Ubuntu 测试环境 |

## 7. 原版尚未修改或未移植的部分

这些部分需要明确写入后续边界，避免项目目标漂移。

### 7.1 有意不移植为必需依赖

| 原版部分 | 当前处理 |
| --- | --- |
| NVIDIA NIM microservices | 不作为必需运行时 |
| NeMo Agent Toolkit / AIQ Toolkit | 不作为必需 agent runtime |
| NVIDIA Docker Compose/Helm/Brev profile | 不作为当前运行方式 |
| NVIDIA VST/VIOS 必需服务 | 不作为 recorded-video baseline 的前置条件 |
| Cosmos/RTVI 必需 embedding/VLM 服务 | 用开放 provider/backend 替代 |
| NGC/NVIDIA API key 作为必需项 | 当前使用 DashScope 或其他 OpenAI-compatible key |

### 7.2 尚未完整移植但可能后续需要

| 原版目录/模块 | 当前状态 | 建议 |
| --- | --- | --- |
| `orchestrator/*` | 当前项目没有对应完整模块 | 当前不做，除非进入生产部署编排 |
| `knowledge_retrieval/*` | 当前没有完整 Enterprise RAG | report 质量阶段后再评估 |
| `tools/vst/*` | 未完整移植 sensor/timeline/snapshot/clip/list | 如果后续需要接摄像头或 VST，再单独开 change |
| `vst_download.py`、`vst_files.py` | 未完整移植 | recorded-video 本地文件优先，暂不急 |
| `lvs_stream_understanding.py` | 未移植流式 LVS | 当前 focus 是本地长视频文件 |
| `lvs_config_media.py`、`lvs_media_state.py` | 未完整移植 | 后续做流/多媒体状态时再补 |
| `rtvi_vlm_alert.py` | 未移植 | 实时告警阶段再做 |
| `tools/code_executor/*` | 未移植 | 当前安全风险高，且不是核心视频业务 |
| 原版 evaluator framework | 只做了简化 evaluator | 业务流稳定后再扩展评分体系 |
| 原版 UI 服务 | 未移植 | 当前只需脚本和日志验收 |
| 原版 analytics 行为分析服务 | 未移植 | 属于下游 analytics，不是下一阶段首要目标 |

## 8. 当前 OpenSpec/Comet 状态

当前活跃 change：

| Change | 状态 | 完成度 | 剩余任务 |
| --- | --- | ---: | --- |
| `unify-live-video-config` | in-progress | 13/14 | `3.3 Add lightweight timing/cost metrics...` |

这说明当前阶段还没有完全收口。最合理的收口方式是：

1. 完成 metrics。
2. 本地跑 unit verification。
3. Ubuntu 跑 shared live video。
4. Ubuntu 跑 graph live video。
5. 对两个 run directory 执行 `python -m vsa_agent validate-run ...`。
6. 如果验证通过，再进入新的 `vss-business-flow-parity` change。

## 9. 当前主要 gap 与风险

### Gap 1: graph 模式还未成为稳定验收门

shared 模式证明“视频能被理解并产出 QA/report”。graph 模式证明“Agent 能自主选择工具”。这两个目标不同。

当前 graph 模式已经有工具调用证据，但还要确认：

- 不再调用隐藏或低层报告工具。
- 不再重复无意义调用 `video_understanding`。
- tool result 错误能被 validator 捕获。
- `top_agent.final` 出现后流程能合理结束。
- QA/report 两段 graph flow 的边界清晰。

### Gap 2: 搜索归档业务还没闭环

当前项目有 search agent 和工具，但下一阶段需要验证一个真实场景：

1. 本地视频或生成的视频片段入库。
2. 生成描述、metadata、时间段、sensor id。
3. 用户自然语言查询。
4. 返回命中的视频片段。
5. 可选 critic 用 VLM 检查命中是否符合 query。

没有这条验收前，不能宣称替代原版 Video Search。

### Gap 3: 长视频有功能但缺运行指标

当前视频约 201 秒时会按 30 秒分块，触发多次 VLM 调用。用户已经观察到运行时间较久。下一阶段必须记录：

- total elapsed。
- video_understanding elapsed。
- chunk elapsed。
- model call elapsed。
- QA elapsed。
- report elapsed。
- 失败重试次数。
- 可用时记录 token usage 或 provider metadata。

没有 metrics，就无法判断是模型慢、分块过多、重复调用、网络慢还是 report 阶段慢。

### Gap 4: report 质量暂时不是第一优先级

报告质量当然重要，但现在更关键的是业务流是否真实发生、是否可验证、是否不重复烧 VLM 额度。报告质量建议放在图模式稳定之后单独做。

### Gap 5: 工作区脏状态较重

当前 git working tree 有大量 modified/untracked 文件，包括代码、测试、docs、openspec、node_modules、.agents、.codegraph 等。下一阶段合入或推送前必须做一次文件归因：

- 哪些是项目源码必须提交。
- 哪些是本地开发工具目录不该提交。
- 哪些是生成 artifacts 不该提交。
- 哪些是文档/计划应该保留。

## 10. 下一阶段开发建议

### P0: 收口当前 `unify-live-video-config`

目标：让当前配置工程和 live-video runner 可以被正式作为后续实验入口。

任务：

- 添加 manifest-level metrics。
- 添加 chunk/model-call timing。
- 本地跑相关 unit tests。
- Ubuntu 跑 shared 模式并 validate。
- Ubuntu 跑 graph 模式并 validate。
- 更新项目状态文档。

验收标准：

- `manifest.json` 有 `metrics`。
- `trace.jsonl` 能说明模型、工具、chunk、错误。
- `python -m vsa_agent validate-run <run_dir>` 能给出 PASS/FAIL。

### P1: 新开 `vss-business-flow-parity`

目标：把“替代原版 recorded-video VSS 业务流”作为新 change 明确管理。

包含范围：

- recorded-video Q&A。
- long-video summarization。
- report generation。
- graph-mode TopAgent acceptance。
- local archive search acceptance。
- run validation。

排除范围：

- real-time alerts。
- Enterprise RAG。
- UI。
- NVIDIA deployment parity。
- 生产级 VST/VIOS 接入。

### P2: 做本地归档搜索验收

目标：证明当前项目不仅能理解单个视频，还能检索视频集合。

最小验收：

- 用 1 到 3 个本地视频或 fixture 构造归档。
- 生成或手写 deterministic description。
- 走 `search_agent`。
- 返回 `SearchOutput`。
- assert video name、description、timestamp、similarity 等字段。

### P3: graph 模式稳定化

目标：让 TopAgent 真正成为自主工具选择入口。

任务：

- 明确工具暴露层级。
- 调整 prompt，避免重复 VLM 调用。
- 限制低层工具直接暴露。
- validator 增强 tool error 捕获。
- graph acceptance 单独记录 QA flow 和 report flow。

### P4: 报告质量提升

目标：在业务流稳定后提升最终交付物可读性。

任务：

- 安全风险提取。
- 时间线整理。
- evidence citation。
- report Markdown 结构化。
- 多视频/多事件报告。

## 11. 建议后续开发顺序

推荐执行顺序：

1. 先完成 `unify-live-video-config` 剩余 metrics。
2. 跑一轮 shared 真实视频，保存 run id，执行 validator。
3. 跑一轮 graph 真实视频，保存 run id，执行 validator。
4. 根据 graph 日志修最后一批工具调用问题。
5. 新开 `vss-business-flow-parity` change。
6. 优先补 local archive search acceptance。
7. 再进入 report quality。

不建议现在做：

- 不建议现在补 UI。
- 不建议现在复刻 NVIDIA Docker/Helm。
- 不建议现在接完整 VST 工具全集。
- 不建议现在做 Enterprise RAG。
- 不建议在 graph 验证未稳定前大量调 report prompt。

## 12. 当前项目完成度判断

| 维度 | 完成度 | 说明 |
| --- | ---: | --- |
| 去 NVIDIA 运行时依赖 | 80% | 核心运行路径已不依赖 NVIDIA，但还有部分原版概念和 optional integration |
| 配置工程化 | 85% | 已统一配置，剩 metrics 和更多 profile 文档化 |
| 单视频 QA | 75% | shared 模式可用，graph 模式需稳定验收 |
| 长视频理解 | 70% | 分块可用，缺性能/成本指标和质量评估 |
| 报告生成 | 60% | 功能可用，质量后置 |
| 视频搜索 | 45% | 模块存在，缺真实归档验收 |
| 可观测性 | 75% | trace/artifacts/validator 已有，缺 metrics |
| 原版完整 parity | 45% | recorded-video baseline 正在接近，高级 VSS 能力仍未移植 |

## 13. 最终建议

当前项目已经走出了最难的第一段：它不再只是原版的浅层仿写，而是有了自己的配置、模型适配、运行脚本、日志产物和真实视频验证方式。

下一阶段不要追求“把原版所有目录都搬过来”。更正确的路线是：

1. 用真实视频和 validator 固化 recorded-video 业务流。
2. 用 local archive search acceptance 补齐搜索闭环。
3. 用 graph mode 证明 TopAgent 自主工具选择。
4. 用 metrics 控制长视频成本和延迟。
5. 等业务流稳定后再提高报告质量、RAG、实时流和生产部署能力。

这条路线最符合项目根本目的：去掉 NVIDIA 依赖，不丢业务价值，并逐步形成真正属于自己的 `vsa-agent`。
