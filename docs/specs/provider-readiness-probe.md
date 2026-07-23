# 真实 Provider Readiness Probe 设计

## 1. 背景与目标

录播生产链路已经能够在 Ubuntu 上完成 Elasticsearch、API、Worker、原版 UI 和同源代理启动，也已经通过 fake-provider 浏览器端到端验收。当前真实 DashScope 验证中，embedding 请求成功，而 VLM 请求返回 `403 AllocationQuota.FreeTierOnly`。现有 runtime doctor 只验证 provider 配置是否完整，不能区分密钥、网络、认证、额度、限流、服务端异常和响应结构问题。

本设计增加一个显式触发、默认不访问外部模型的 readiness probe。用户继续只操作 `scripts/es-runtime-stack.sh` 或 `scripts/es-runtime-stack.ps1`，即可在不启动 Elasticsearch、API、Worker 和 UI 的情况下验证真实 VLM 与 embedding provider。

目标：

- 复用生产栈相同的配置解析、`api_key_env` 和私密文件加载规则。
- 分别执行最小 VLM 与 embedding 请求，给出稳定、可机器读取的诊断结果。
- 日志足以定位认证、额度、限流、超时、网络、HTTP 5xx 和响应结构问题。
- 不记录密钥、Authorization、完整响应正文、提示词或向量内容。
- 默认栈启动行为不变，不因诊断功能增加额外模型调用或费用。

## 2. 方案选择

采用“单入口显式探针”方案：

- `es-runtime-stack.sh` 与 `es-runtime-stack.ps1` 增加 `--probe-providers` / `-ProbeProviders`。
- 启动器先使用现有安全逻辑加载私密配置，再调用 runtime doctor 的 live provider probe，然后退出。
- runtime doctor 承担结构化诊断，启动器承担密钥文件加载和统一日志输出。

不采用独立用户入口，以免增加需要记忆的脚本。不在普通启动时自动探测，避免每次启动产生外部费用，也避免临时供应商故障妨碍本地 ES、API 或媒体诊断。

## 3. 命令契约

Ubuntu：

```bash
./scripts/es-runtime-stack.sh \
  --config config.yaml \
  --conda-env vsa-agent \
  --probe-providers
```

Windows：

```powershell
.\scripts\es-runtime-stack.ps1 \
  -Config config.yaml \
  -CondaEnv vsa-agent \
  -ProbeProviders
```

若启动器当前没有公开 `--config` / `-Config`，本次实现应增加该参数并保持默认值为仓库根目录 `config.yaml`。探针模式不得启动或终止任何端口进程，不得启动 Docker、Elasticsearch、API、Worker 或 UI，也不得创建生产索引和录播任务。

runtime doctor 增加显式 live probe 参数；该参数只由启动器或直接诊断命令触发。未传入时，原有静态与 Elasticsearch doctor 行为不变。

## 4. 配置与密钥流

1. 启动器解析配置路径和私密文件路径。
2. 启动器使用现有严格解析器读取 `~/.config/vsa-agent/secrets.env`，仅接受 `*_API_KEY=VALUE`，并拒绝宽松权限、错误 owner、空值和非法变量名。
3. AppConfig 合并 `config.yaml` 与同目录的 `config.local.yaml`，解析 active profile、VLM、embedding backend、model、base URL 和 `api_key_env`。
4. runtime doctor 只从对应环境变量取密钥；报告中只记录 role、provider、model、host，不记录 key 值。
5. 探针结束后进程退出，环境变量不写入磁盘、manifest、报告或子进程参数。

探针必须沿用生产录播的 fail-closed 规则：active profile 必须存在；VLM 与 embedding 均必须配置；mock fallback 与 forced mock embedding 必须关闭；所需 `api_key_env` 必须有非空值。

## 5. Provider 请求

### 5.1 Embedding

- 请求 OpenAI-compatible `/embeddings`。
- 使用 active embedding model。
- 输入固定、非敏感的短文本 `production readiness probe`。
- 成功条件：HTTP 200，响应包含至少一个非空、有限数值向量。
- 不记录输入、向量长度以外的响应内容或向量值。

### 5.2 VLM

- 请求 OpenAI-compatible `/chat/completions`。
- 使用 active VLM model。
- 发送最小文本消息并限制 `max_tokens`，不上传视频、图片或用户业务内容。
- 成功条件：HTTP 200，响应包含非空 assistant message。
- VLM readiness 只证明模型接口可调用；完整视频语义正确性仍由三视频生产验收证明。

两个请求依次执行，避免额外并发和配额压力。单个请求使用明确超时，完成后关闭 HTTP client。

## 6. 诊断模型与退出码

每个 role 产生一条结构化结果：

```text
provider_probe role=vlm outcome=quota status=403 duration_ms=158 provider_code=AllocationQuota.FreeTierOnly request_id=<safe-id>
```

结果字段：

- `role`: `vlm` 或 `embedding`。
- `outcome`: `ok`、`configuration`、`authentication`、`quota`、`rate_limit`、`timeout`、`network`、`server_error`、`response_schema` 或 `http_error`。
- `status`: HTTP 状态；网络层失败为 `none`。
- `duration_ms`: 单次请求耗时。
- `provider_code`: 供应商错误码，仅允许字母、数字、点、下划线和连字符，限制长度。
- `request_id`: 从批准的响应头读取并执行同样的字符白名单和长度限制。

所有 role 都执行，以便一次看到完整状态；任一 role 失败则整体返回非零。CLI 的稳定退出码为：

- `0`: VLM 与 embedding 均通过。
- `2`: 配置或密钥问题。
- `3`: 认证或额度不可用。
- `4`: 限流、超时、网络或服务端暂态问题。
- `5`: HTTP 契约或响应结构错误。

当两个 role 失败类型不同，整体退出码按 `2 > 3 > 4 > 5` 的优先级选择；逐 role 日志仍保留全部原因。

## 7. 日志与安全

- 启动器终端与 run 日志均使用 `[stack]` 和 `[doctor]` 前缀。
- runtime doctor 的 `--json` 输出只包含上述安全字段和非敏感 provider identity。
- 不输出响应正文、请求 JSON、Authorization、密钥长度、密钥前后缀、完整 URL 查询串、prompt、assistant 内容或 embedding 值。
- `provider_code` 与 `request_id` 必须先做类型检查、字符白名单和长度限制。
- 异常文本只记录异常类型和稳定 outcome，不直接拼接第三方异常字符串。
- 单元测试必须用 canary secret 扫描 stdout、stderr、JSON 和日志，确保没有泄露。

## 8. 代码边界

- provider 请求与分类逻辑放在 `src/vsa_agent/recorded_video/provider_probe.py`，保持纯粹、可测试，不依赖启动器全局状态。
- `scripts/runtime-doctor.py` 只负责参数、配置解析、调用 probe 和渲染文本/JSON结果。
- Bash/PowerShell 启动器只负责现有密钥加载、参数转发、统一日志和退出码传播。
- 复用现有 provider URL 校验、配置解析和安全字段清洗规则；只有在避免循环依赖时才提取小型共享 helper。
- 不修改录播 Worker pipeline、Elasticsearch schema、原版 UI 或正常栈生命周期。

## 9. 测试与验收

单元测试覆盖：

- VLM 与 embedding 均成功。
- DashScope `AllocationQuota.FreeTierOnly` 分类为 `quota`，整体退出码为 `3`。
- 401/403 认证失败、429 限流、408/客户端超时、网络错误、5xx 和未知 4xx。
- HTTP 200 但 VLM/embedding 响应结构无效。
- provider code 与 request ID 字符过滤、截断和非字符串处理。
- canary secret 不出现在文本、JSON、日志或异常信息中。
- 默认 runtime doctor 和默认启动器不发起网络请求。
- probe 模式不调用 Docker、不回收端口、不启动任何栈组件。
- Bash/PowerShell 参数和退出码契约一致。

Ubuntu 验收分两层：

1. 当前 DashScope 额度未恢复时，embedding 输出 `ok`，VLM 输出 `quota`，命令返回 `3`，且日志 secret scan 通过。
2. 额度恢复后，两项均输出 `ok` 并返回 `0`；随后立即执行 `recorded-video-production-acceptance.py`，以三个真实视频证明上传、Worker 中断恢复、ES publish、原版 UI 搜索、缩略图、Range 播放、选中片段视频理解问答和删除。

provider probe 成功不是最终生产验收的替代品。

## 10. 文档与交付

- 更新 `docs/recorded-video-runtime.md`，增加探针命令、退出码和故障处理表。
- 更新 `docs/DEVELOPMENT_STATUS.md`，记录当前 embedding PASS、VLM quota 状态以及探针证据。
- 同步新增源码、测试和文档到 `Z:\vsa-agent` 白名单。
- 本地质量门、Ubuntu 单元测试和真实 DashScope 探针通过预期后，合并并推送 `master`。
- DashScope VLM 额度恢复并完成三视频真实 UI 验收前，不宣称最终目标完成。
