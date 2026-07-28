# 真实业务视频回归基线设计

状态：已确认，等待实施计划
日期：2026-07-28

## 1. 背景

项目已经在 Ubuntu 服务器上完成录播视频上传、Worker 处理、真实 VLM/embedding、Elasticsearch 搜索、媒体播放和原版 UI 选中片段问答验证。现有生产验收主要证明链路能够运行，Playwright fixture 主要使用 FFmpeg 合成画面；这些测试不能回答模型对叉车、人员接近和 PPE 场景的业务判断是否正确。

本设计建立一个小型、可追溯、可重复运行的真实业务视频基线。视频来自公开网络，二进制只保存在服务器；Git 保存来源、许可、哈希、片段标注、预期结论和运行证据契约。

## 2. 目标

首版必须做到：

1. 使用许可明确的真实实拍视频替代生产业务准确性验收中的合成视频。
2. 覆盖叉车接近人员、叉车安全分离、人员近距离协同风险、普通人员作业对照、PPE 合规、PPE 缺失或使用不当六个场景。
3. 通过现有录播视频生产链路验证上传、切分、真实 Provider、Elasticsearch、媒体和 Chat。
4. 使用确定性概念门禁评估结果，LLM-as-judge 只能提供辅助诊断，不能单独决定通过。
5. 提供快速片段回归和完整原视频回归两个层级。
6. 保留完整、可审计且不含密钥的日志和结构化报告。
7. 不引入与 NVIDIA 依赖去除目标无关的数据集平台、实验平台或前端依赖。

## 3. 非目标

首版不包含：

- 将视频二进制提交到 Git 或引入 Git LFS。
- 建设通用数据标注平台或模型训练数据集。
- 以单一总分替代逐用例门禁。
- 要求模型使用指定语言、固定句式或固定报告格式回答。
- 用真实 Provider 回归替代所有快速、离线的合成 UI 测试。
- 在首版中完成大规模现代 CCTV 数据集建设。

## 4. 已选方案

采用 manifest 驱动的独立业务基线。

真实业务准确性测试与普通 UI 结构测试分离。业务基线运行器复用现有 `vsa_agent.recorded_video.production_acceptance`、`production_evidence`、录播视频 API、搜索接口和 evaluator 能力。原版 UI 只增加一条代表性真实链路 Playwright 验证，不承载整个数据集的准确性计算。

未采用以下方案：

- 直接替换所有 Playwright 合成 fixture：会把 UI 稳定性、网络下载、真实 Provider 成本和业务准确性混在一起。
- 引入外部实验管理或数据集平台：首版成本过高，并会带来不相关依赖。

## 5. 数据来源策略

采用两阶段混合来源：

1. 首版硬基线使用许可明确、可稳定下载的政府或公共机构实拍培训视频。
2. 后续补充许可同样明确的现代仓库、工地或监控摄像头风格视频，提高生产画面代表性。

首版已找到以下候选：

| 候选 | 来源机构 | 网络条目 | 许可 | 用途 |
| --- | --- | --- | --- | --- |
| Forklift pedestrian safety | Washington State Department of Labor & Industries | `https://archive.org/details/youtube-NbjX7GIUT-o` | CC BY 3.0 | 叉车接近人员、安全分离 |
| Surveying Safety | Iowa Department of Transportation | `https://archive.org/details/youtube-fZyAxVtTw4U` | CC BY 3.0 | 人员协同、普通作业、PPE |
| Protecting workers in auto body shops | U.S. NIOSH | `https://archive.org/details/youtube-HFAT2XWAVTw` | CC BY 3.0 | PPE 合规与不当使用 |

候选标题或说明不能直接成为标注。实施时必须下载原文件、生成联系表、查看目标时间段并确认画面。若某个候选无法提供清晰正负对照，则从许可同样明确的网络来源替换该候选，不得降低六场景要求。

下载器只能使用 manifest 中已审查的直链，不绕过登录、反爬或访问控制。每个来源必须记录来源页、下载 URL、作者或机构、许可标识、许可 URL、归属文本、获取日期、媒体规格和 SHA-256。

## 6. Manifest 设计

建议仓库路径为 `tests/fixtures/business_video_baseline/manifest.yaml`。manifest 使用版本化严格 schema，并拒绝未知字段。

### 6.1 数据集字段

- `schema_version`：schema 版本。
- `dataset_id` 和 `dataset_version`：稳定数据集标识与版本。
- `license_policy`：允许的许可集合和归属要求。
- `profiles`：快速层与发布层的执行策略。

### 6.2 来源字段

- `source_id`：稳定来源 ID。
- `source_page_url`、`download_url`：来源证据与下载地址。
- `creator`、`publisher`、`published_at`：创作者和发布信息。
- `license_id`、`license_url`、`attribution`：许可和归属。
- `retrieved_at`：获取日期。
- `sha256`、`size_bytes`、`duration_sec`、`width`、`height`、`codec`：固定媒体身份。

### 6.3 用例字段

- `case_id`、`source_id`、`scenario`：用例身份和场景。
- `clip.start_sec`、`clip.end_sec`、`clip_filename`：原视频片段和派生文件。
- `search_queries`、`chat_queries`：不绑定输出语言的业务问题。
- `required_concept_groups`：每组列出同义表达；同组命中一个表达即视为该概念命中。
- `forbidden_concepts`：会导致用例失败的错误结论。
- `expected_asset` 和 `expected_window`：搜索目标和原视频时间范围。
- `required`：核心六场景必须为 `true`。
- `tags`：正例、负例、叉车、人员接近、PPE 等分类。

schema 必须拒绝重复 ID、片段越界、空查询、空概念组、缺失许可、非法 SHA-256 和必选用例被标为可选。

## 7. 组件与边界

### 7.1 数据准备器

建议入口为 `scripts/prepare-business-video-baseline.py`。它只负责：

1. 校验 manifest 和许可字段。
2. 下载或复用缓存原视频。
3. 计算并严格校验 SHA-256。
4. 使用项目已有 FFmpeg/ffprobe 生成片段并获取媒体信息。
5. 计算派生片段哈希，写出 resolved manifest 和准备日志。

准备器不得自动接受变化后的远程文件哈希。更新哈希必须经过重新查看画面、核对许可和重新标注。

### 7.2 业务基线 evaluator

建议在 `src/vsa_agent/evaluators/` 中扩展现有确定性 evaluator，而不是在脚本中实现字符串规则。其职责为：

- 规范化大小写、空白和可配置同义词。
- 计算概念组覆盖率。
- 检测禁止结论。
- 验证搜索结果资产身份、Top-K 排名和时间重叠。
- 聚合多次 Provider 运行，但保留每次原始判定。
- 生成稳定的结构化判定模型。

现有 `evaluate_understanding_result` 的 `summary_terms` 和事件匹配能力可以复用，但首版需要增加“同义概念组”“禁止概念”和允许时间容差，不能要求固定句子或精确时间字符串。

### 7.3 回归运行器

建议入口为 `scripts/run-business-video-regression.py`，核心逻辑放在可单元测试的 `src/vsa_agent/recorded_video/` 模块。运行器负责：

- 加载 resolved manifest 和指定 profile。
- 为本次运行创建独立 `run_id`、data root 和 Elasticsearch alias/index。
- 调用现有录播上传 API并等待 Worker 七阶段处理完成。
- 限定本次资产执行搜索和 Chat。
- 调用 evaluator 并收集生产证据。
- 清理本次资产、索引和进程。
- 输出 JSON、JUnit 和终端摘要。

启动器只负责启动依赖和调用入口，不承载 manifest 解析或准确性规则。

### 7.4 原版 UI 验证

增加一条真实 Provider Playwright 用例，使用一个代表性叉车片段完成：

1. 从原版 UI 上传视频。
2. 等待任务完成。
3. 搜索叉车与人员接近场景。
4. 打开命中视频并验证媒体可播放。
5. 将正确片段加入 Chat 上下文。
6. 提交业务问题并获得符合概念门槛的回答。

Playwright 在 Ubuntu 服务器本机访问 UI/API，因此自动验收不依赖用户本机 SSH 隧道。人工验证仍可通过 SSH 端口转发访问相同服务。

## 8. 执行数据流

```text
manifest 与许可预检
  -> 下载原视频并校验 SHA-256
  -> FFmpeg 生成真实短片段并校验
  -> 创建隔离 run_id/data-root/ES alias
  -> 上传视频并等待切分、Provider 和索引完成
  -> 执行限定当前资产的搜索
  -> 验证 Top-5、资产身份和时间范围
  -> 将正确搜索结果加入 Chat 上下文
  -> 验证必须概念和禁止结论
  -> 写出证据与报告
  -> 清理本次运行资源
```

快速层上传派生片段；完整层上传原始视频，并根据上传资产的时间锚点把 manifest 中的秒偏移转换为搜索返回时间。允许的切分误差为标注区间前后各 5 秒。

搜索请求必须使用本次上传的资产 ID 进行过滤。历史生产数据即使内容相似，也不能满足本次用例。

## 9. 场景矩阵

首版固定六个核心用例：

| 场景 | 类型 | 主要必须概念 | 主要禁止结论 |
| --- | --- | --- | --- |
| 叉车接近人员 | 风险正例 | 叉车、人员、接近或共享行进区域 | 没有人员、没有叉车、完全隔离 |
| 叉车安全分离 | 风险负例 | 叉车、人员、存在隔离或安全距离 | 正在碰撞、人员已被撞击 |
| 人员近距离协同 | 风险正例 | 多人、近距离、协同搬运或作业 | 只有一人、现场无人 |
| 普通人员作业 | 风险负例 | 人员、正常作业、未见明确接近事件 | 已发生碰撞或严重事故 |
| PPE 合规 | 合规正例 | 人员、场景所需 PPE、正确佩戴或使用 | 未佩戴任何 PPE |
| PPE 缺失或不当 | 不合规正例 | 人员、缺失或错误使用具体 PPE | PPE 完全合规 |

最终同义词和禁止表达必须以联系表所见画面为依据写入 manifest。禁止概念只约束事实性错误，不约束措辞、报告结构或语言。

## 10. 门禁与重复策略

### 10.1 快速层

- 每个核心片段运行一次真实 Provider。
- 搜索 Top-5 必须包含正确资产。
- 命中时间允许相对标注区间前后各 5 秒。
- 必须概念组覆盖率至少 80%。
- 禁止结论为零。

### 10.2 发布层

- 每个核心用例独立运行三次 Provider。
- 至少两次达到 80% 必须概念覆盖率。
- 三次均不得出现禁止结论。
- 搜索、媒体和 Chat 链路每次都必须成功。
- 六个用例逐项通过；总体平均分不能抵消单个用例失败。

### 10.3 完整视频层

- 上传完整原视频，验证长视频切分、任务恢复和事件窗口检索。
- manifest 中每个标注事件窗口必须可从完整视频搜索命中。
- 该层定期或人工执行，不放入普通本地测试。

HTTP 瞬时重试与 Provider 三次运行分别计数。HTTP 重试不得生成新的模型准确性 attempt；模型每次真实输出都必须保留。

## 11. 失败分类

- `dataset_error`：许可缺失、下载失败、哈希漂移、片段越界、媒体探测或 FFmpeg 失败。发生后在 Provider 调用前停止。
- `pipeline_error`：API、Worker、Provider 请求、Elasticsearch、媒体或 Chat 链路失败。
- `accuracy_failure`：Top-5 未命中、时间超差、概念覆盖不足或出现禁止结论。
- `cleanup_error`：资产、隔离索引或运行进程未能清理。
- `skipped`：仅限 manifest 明确可选且环境确实缺少对应能力的用例。

六个核心用例在发布配置中不可跳过。发布层出现上述任一错误均失败；清理错误不能被降级成普通警告。

建议退出码：

- `0`：通过。
- `2`：数据集或参数错误。
- `3`：流水线或基础设施错误。
- `4`：业务准确性失败。
- `5`：清理失败。

## 12. 证据与日志

每次运行写入：

```text
.runtime/business-video-regression/<run_id>/
  resolved-manifest.yaml
  preparation.log
  runner.log
  report.json
  junit.xml
  cases/<case-id>/<attempt>.json
```

报告包含：

- Git 提交、数据集版本和运行 profile。
- 视频与片段哈希。
- 已脱敏的 Provider/模型配置指纹和请求 ID。
- 上传任务、搜索结果、排名、相似度、时间范围和媒体检查。
- 每次 Chat 原始回答、概念命中、禁止结论和最终判定。
- 每阶段耗时、重试、清理结果和最终失败分类。

API Key 不得进入命令参数、报告、日志或测试附件。终端摘要可以本地化；测试只依赖稳定的 JSON/JUnit 字段，不把终端摘要或模型回答的自然语言作为契约。

## 13. 测试策略

### 13.1 单元测试

不访问网络或真实 Provider，覆盖：

- manifest 严格校验和错误消息。
- 同义概念组、80% 覆盖、禁止结论。
- Top-5、资产身份、时间重叠和 5 秒容差。
- 快速层单次判定和发布层 2/3 聚合。
- 失败分类、退出码、脱敏和报告 schema。

### 13.2 模拟集成测试

使用固定 API 响应覆盖上传、任务轮询、搜索、媒体、Chat、瞬时重试、超时、部分失败和清理。测试必须证明 HTTP 重试不会被错误计为 Provider attempt。

### 13.3 Ubuntu 真实回归

仅在已配置真实密钥的 Ubuntu 服务器运行。使用全新隔离 data root 和 ES alias，先执行快速六片段回归，再按需执行发布层和完整视频层。

### 13.4 原版 UI E2E

普通合成 fixture 继续用于快速 UI 行为测试；代表性真实叉车用例作为独立、显式启用的真实 Provider E2E。两者报告分开，避免把真实 Provider 波动归因于 UI 回归。

## 14. 发布验收标准

首版完成必须同时满足：

1. 三个或更多公开来源通过许可、来源页和 SHA-256 固定。
2. 六个核心用例均完成画面审查并写入 manifest。
3. 数据准备命令可重复运行，缓存命中时仍会重新校验哈希。
4. 本地单元和模拟集成测试通过。
5. Ubuntu 快速层六个用例全部通过且无跳过。
6. Ubuntu 发布层满足逐用例 2/3 概念门禁和三次零禁止结论。
7. 完整视频层能找回全部标注窗口。
8. 原版 UI 真实叉车链路通过上传、搜索、播放、Chat 上下文和回答验证。
9. 没有数据哈希漂移、流水线错误、清理错误或密钥泄露。
10. JSON 和 JUnit 报告完整，失败可以定位到用例、attempt 和阶段。

## 15. 后续升级路径

首版通过后按以下顺序扩展：

1. 增加许可明确的现代仓库和工地监控风格片段。
2. 增加叉车盲区、高处作业、跌落、禁区进入等场景。
3. 基于稳定运行数据收紧 Top-K、时间容差和概念覆盖门槛。
4. 增加人工复核后的语义评分，但仍不让 LLM-as-judge 成为唯一硬门禁。
5. 建立定期完整视频回归和趋势报告。

每次数据集升级都必须提升 `dataset_version`，重新固定哈希，并保留旧版本报告用于纵向比较。
