# 本地 VLM 视频隐私与资源准入设计

状态：本地实施与自动化验证完成，待 Ubuntu 真实验收
确认日期：2026-07-30
目标平台：Ubuntu 单机，NVIDIA GeForce RTX 4090 D 24GB，无管理员权限

## 1. 目标

本设计把视频理解迁移到服务器本地 vLLM，同时保留 DashScope 文本 LLM 和 embedding API。系统必须满足：

- 原始视频、切片、抽帧、视觉提示词和本地视觉证据不得离开服务器。
- 所有远程 LLM 与 embedding 调用都经过同一个类型安全的出站边界。
- 每次一键启动前都检查 GPU、系统内存、磁盘、模型、端口和进程归属。
- 资源不足或归属不明时拒绝启动，不终止其他用户或其他项目的进程。
- vLLM 使用独立用户级环境，由现有运行栈统一监管和记录日志。
- 容量门槛由保守公式和真实 warm-up 校准共同决定，不能依靠 OOM 探测。

## 2. 明确不做

首版不包含多 GPU、张量并行、自动切换小模型、远程视觉回退、公共网络暴露、容器化 vLLM、自动驱动安装或管理员权限操作。资源不足时不会排队等待，也不会抢占未知 GPU 进程。

## 3. 已确认决策

| 项目 | 决策 |
|---|---|
| 本地视觉模型 | 官方 `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` |
| 文本 LLM | DashScope API |
| Embedding | DashScope API，仅处理远程安全投影 |
| 资源不足 | Fail closed，输出缺口后退出 |
| 模型准备 | bootstrap 与日常启动分离 |
| 日常启动 | 严格离线，不安装、不下载、不解析远程 revision |
| VLM 并发 | 1 |
| 最大图像数 | 每次请求硬上限 24；正常采样可低于该值 |
| 上下文 | 16K，文本输入最多 4096 tokens，输出最多 1024 tokens |
| 隐私 | 远程只接收封闭枚举和数值组成的安全 DTO |
| 部署方式 | 独立 `vsa-vllm` 环境，由统一脚本监管 |

## 4. 当前系统差距

项目已有 OpenAI-compatible vLLM adapter，视频理解调用层不需要重写，但现状不能满足本设计：

- `local_vllm` 与业务 API 都使用 8000，存在端口冲突。
- 运行栈不负责 vLLM 的资源准入、启动、健康检查和退出清理。
- 当前端口回收逻辑允许终止任意同 UID 占用者，不能证明项目归属。
- 当前进程 manifest 没有内核启动 tick、boot ID、实际 workload PID、PGID 或 SID，不能防止 PID 复用。
- 录播 pipeline 会把 VLM 自由文本 `description` 直接发送到远程 embedding。
- 搜索分解、embedding、critic、TopAgent 和历史消息都可能把本地元数据再次发给远程 LLM。
- 当前短视频、长视频和录播任务使用不同帧数，并且部分路径没有兑现像素上限。
- 当前阶段级 checkpoint 不能保证片段级恢复，也没有持久化的隐私投影阶段。

实施必须同时关闭这些绕过路径；只修改一个 ingestion 调用点不算完成。

## 5. 总体架构

```text
本地视频
  -> 本地切片/抽帧/缩放
  -> 本地 vLLM VLM
  -> 本地完整分析结果
  -> 版本化隐私投影
       -> 远程安全事件 -> DashScope embedding
       -> 远程安全上下文 -> DashScope LLM
  -> 本地 Elasticsearch / SQLite / 媒体存储
  -> 本地 renderer 用 opaque result_ref 回填文件名、绝对时间和媒体地址
```

组件职责：

- `bootstrap-local-vlm.sh`：创建独立环境，下载、校验并固定模型。
- `es-runtime-stack.sh`：日常唯一启动入口，依次执行准入、vLLM、ES、API、Worker、UI。
- 本地 VLM adapter：只允许 loopback endpoint，不得回退到远程视觉 provider。
- `RemoteProviderGateway`：DashScope LLM 与 embedding 的唯一出口，只接受 `RemoteSafe*` DTO。
- 隐私投影器：把本地完整结果转换为版本化、封闭、可审计的远程安全数据。
- 本地 renderer：在远程推理完成后解析 opaque reference，并在服务器内回填本地展示字段。

运行配置使用一个显式 hybrid profile：

```text
active_profile = local_vlm_hybrid
llm       -> DashScope / qwen-turbo
vlm       -> local vLLM / qwen2.5-vl-local / http://127.0.0.1:8001/v1
embedding -> DashScope / text-embedding-v4
```

三个角色都必须存在并通过 runtime readiness。vLLM backend 不要求远程 API key；DashScope 密钥继续只从服务器用户私有 secrets 文件注入。配置验证必须拒绝本地 VLM 与业务 API 端口冲突、非 loopback VLM URL、缺失 embedding role 或任何 mock/test-only provider。

## 6. 模型供应链与 bootstrap

模型固定为：

```text
repository: Qwen/Qwen2.5-VL-7B-Instruct-AWQ
revision: 536a35794df8831aa814970ee8f89eff577e7718
license: Apache-2.0
quantization: AWQ 4-bit
AWQ format: W4A16, group_size=128, zero_point=true, version=gemm
```

权重分片：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `model-00001-of-00002.safetensors` | 3,982,163,944 | `4f75e3de726546ee43620d1227d3596cd3ba0fdd19f11faeea71de578d2d1052` |
| `model-00002-of-00002.safetensors` | 2,941,808,440 | `dae4128bbfd2b8d489e838048edc0bbe6e31f269d9b96fa3effe11cc534b8f0c` |

两个权重分片合计 6,923,972,384 字节，约 6.4485 GiB；完整仓库下载量为 6,939,964,850 字节，约 6.4633 GiB。bootstrap 必须对 snapshot 的全部 16 个文件生成并校验 SHA-256 manifest。

bootstrap 要求：

1. 只使用当前普通用户权限，创建独立 `vsa-vllm` Conda 环境。
2. 首版固定 `vLLM 0.8.5`、`Torch 2.6/cu124` 和兼容的 Transformers/AWQ 依赖，生成包含包哈希的 lock manifest；独立环境必须设置 `PYTHONNOUSERSITE=1` 并通过 `pip check`，不得借用用户级 site-packages；服务器驱动 `550.163.01` 的 CUDA capability 为 12.4，禁止安装默认要求 CUDA 12.8 的 wheel。
3. 下载到项目外的模型目录，例如 `/data/project/lyk/models/vsa-agent/`。
4. 先下载临时 snapshot，完成大小和 SHA-256 校验后再原子发布。
5. 生成只读模型 manifest，记录仓库、revision、许可证、文件哈希和依赖指纹。
6. 执行一次 vLLM import、CUDA 可用性和模型配置兼容探测。
7. 重复执行必须幂等；已校验内容不得重复下载。

日常启动设置 Hugging Face 与 Transformers 离线模式并关闭 telemetry。模型不存在、manifest 不匹配或哈希失败时直接退出，不在启动流程内修复或联网。

## 7. GPU 显存预算

服务器实测总显存为 24,564 MiB。首版参数：

```text
gpu_memory_utilization = 0.70
max_model_len = 16384
max_num_seqs = 1
max_num_batched_tokens = 16384
max_frames = 24
max_pixels_per_image = 200704   # 448 * 448
dtype = half
enforce_eager = true
cpu_offload_gb = 0
swap_space_gb = 0
```

vLLM 引擎计划预算：

```text
engine_budget_mib = ceil(24564 * 0.70) = 17195 MiB
safety_reserve_mib = 4096 MiB
required_free_mib = engine_budget_mib + safety_reserve_mib = 21291 MiB
recommended_free_mib = engine_budget_mib + 6144 MiB = 23339 MiB
```

当前调研快照为空闲 24,211 MiB，因此能通过硬门槛和推荐门槛。若引擎达到计划预算，预计仍有约 7,016 MiB 空闲。禁止使用与引擎预算无关的固定 20 GiB 门槛。

显存构成用于解释容量，不作为单独硬编码分项：

- AWQ 权重约 6.45 GiB，另有量化元数据。
- CUDA context、视觉编码器、算子工作区和临时激活约 3-5 GiB。
- Qwen2.5-VL-7B 为 28 层、4 个 KV heads、128 head dimension；16K 单序列 BF16 KV 的逻辑最低需求约 0.875 GiB。
- vLLM 会把引擎预算内的剩余空间继续分配给 KV blocks，因此稳定显存占用可能接近完整的 17,195 MiB，而不是上述分项的简单最小和。
- AWQ W4A16 在选定 vLLM 基线中要求 FP16 activation；必须显式使用 `dtype=half`，避免 `auto` 从模型配置选择 BF16 后启动失败。

校准后的硬门槛为：

```text
max(engine_budget_mib + 4096, measured_project_peak_delta_mib + 2048)
```

校准只能提高门槛，不能降低公式门槛。若峰值加 2 GiB 已超过物理可用显存，则该参数组合判定为不安全，不能发布。

## 8. 图像和 token 容量

Qwen2.5-VL 的视觉 patch 为 14，spatial merge 为 2。448 x 448 图像的近似视觉 token 为：

```text
448 / 14 / 2 = 16
16 * 16 = 256 visual tokens per image
24 images = 6144 visual tokens
```

加上视觉特殊 token、最多 4096 文本输入和最多 1024 输出，仍在 16K 上下文内。公式只用于静态预算，最终以固定 processor 实际返回的 token 数为准。

所有调用路径必须同时执行：

- 应用层保持纵横比缩放，单图不得超过 200,704 pixels。
- vLLM `mm_processor_kwargs.max_pixels` 使用相同上限，形成服务端第二道约束。
- 请求前检查图像数、单图像素、文本 token 和总 token。
- 任一上限超出时，在请求进入 vLLM 前返回明确容量错误。
- 24 是服务硬上限和校准压力值，不要求每个任务都抽取 24 帧；现有 4/10/12 帧策略可由统一采样接口配置，但不得绕过硬上限。

## 9. 系统内存、共享内存与磁盘

有效可用内存不能只读取 `/proc/meminfo`，应计算：

```text
min(MemAvailable, cgroup_v2 memory.max - memory.current, finite RLIMIT_AS headroom)
```

同时检查 `/dev/shm`。规则为：

- 有效可用内存低于 24 GiB：拒绝启动。
- 24-32 GiB：允许启动但输出警告。
- warm-up 后 `MemAvailable` 必须仍不低于 16 GiB。
- warm-up 期间新增 swap 使用不得超过 256 MiB。
- `cpu_offload_gb=0`、`swap_space_gb=0`，避免未计入预算的隐式占用。

磁盘按目标文件系统分别检查：Conda 环境所在文件系统、模型目录、业务 data root 和运行日志目录不能用一个 `df` 结果代替。bootstrap 时模型文件系统和环境文件系统分别至少需要 20 GiB；若二者相同则需要 40 GiB。日常启动要求模型卷至少剩余 10 GiB、业务数据和日志卷至少剩余 15 GiB，并根据模型 manifest 实际字节数检查，不能把政策门槛描述成模型真实体积。

## 10. 校准指纹与流程

校准指纹必须包含：

- 模型 repository、revision、配置哈希和权重 manifest 哈希
- GPU UUID、型号、NVIDIA driver、CUDA runtime
- Python、Torch、vLLM、Transformers 和量化依赖版本
- quantization、dtype、KV dtype、CUDA graph/eager 模式
- `max_model_len`、`max_num_seqs`、`max_num_batched_tokens`
- 图像数、像素上限、`limit_mm_per_prompt`、`mm_processor_kwargs`
- VLM prompt、视觉 schema 和采样策略版本

缺少校准或指纹变化时，使用保守公式准入，并执行固定的非敏感校准：连续 3 次全新 vLLM 冷启动，每次处理 3 个最大负载请求；每个请求使用 24 张最大像素合成图像、最大文本预算和 1024 输出预算。从 vLLM 进程创建前开始，以不超过 250ms 的周期采样项目 PID 显存、全卡空闲显存、GPU utilization、进程 RSS、系统内存和 swap。

warm-up 必须无 OOM、无进程重启、无 GPU Xid，结束后 GPU 空闲不得低于 4096 MiB。校准记录原子写入，并只对完全相同的指纹有效。

## 11. 启动状态机

日常一键启动顺序：

1. 在创建 run、修改 `latest` 或回收资源前取得跨进程 `flock`，锁持有到 cleanup 完成。
2. 读取旧 manifest，只清理能完整证明属于本项目的进程。
3. 检查模型 manifest、离线环境、目录权限、磁盘、端口和系统内存。
4. 连续采样 GPU 3 次，取最低空闲显存和最高 utilization。
5. 按 GPU UUID 选择设备并设置 `CUDA_VISIBLE_DEVICES`。
6. 满足准入后启动受监管 vLLM。
7. 等待 `/health`，校验 `/v1/models` 中的 served model，再运行非敏感单帧探针。
8. 必要时完成容量校准。
9. 依次启动 ES、API、Worker 和原版 UI。
10. 写入运行证据并持续监管；任一必需组件退出时整栈失败并清理。

准入阶段不允许出现“只启动 UI/API、VLM 不可用”的部分成功状态。

## 12. GPU 准入规则

`nvidia-smi` 必须提供 GPU UUID、型号、总显存、空闲显存、utilization 和 compute process。缺字段、`N/A`、解析失败或工具不可用都拒绝启动。

规则：

- 空闲显存低于动态硬门槛：拒绝。
- 三次采样中的最高 utilization 超过 10%：拒绝。
- 存在未由项目 manifest 证明归属的 compute process：拒绝，即使同 UID 或显存仍够。
- 不终止未知进程，不调用 `sudo`，不修改 GPU 持久化模式。
- preflight 与 vLLM 分配显存之间仍存在竞态；初始化失败后必须重新采样，保存资源变化证据并清理本次进程。

失败输出至少包含 GPU UUID、总量、空闲、要求、缺口、utilization、占用 PID/命令摘要、有效系统内存、校准指纹和拒绝规则。

## 13. 进程归属、端口与退出

每次运行目录：

```text
.runtime/es-stack/runs/<run-id>/
  process-manifest.json
  preflight.json
  runtime-evidence.json
  launcher.log
  vllm.log
  api.log
  worker.log
  ui.log
```

manifest 对 supervisor 和实际 workload 分别记录 PID、UID、`/proc/<pid>/stat` 启动 tick、boot ID、exe、cwd、cmdline 摘要、run ID、SID 和 PGID。只有全部身份字段匹配才允许发送信号；同 UID、相同进程名或命令包含仓库路径都不能单独证明归属。

vLLM workload 在独立 session 中运行并禁用 daemon/Ray 等不可监管派生模式。启动使用握手 gate：workload 在初始化 GPU 前等待，launcher 先原子写入身份 manifest，再释放 gate，消除“进程已经占用 GPU 但尚未登记”的窗口。

端口检查先判断监听是否存在，再尝试解析 PID。应覆盖回环、IPv4/IPv6 wildcard 和 `SO_REUSEPORT` 风险；监听存在但无法识别归属时拒绝启动。bind 竞态仍按正常启动失败处理并保留日志。

Elasticsearch 若仍由 Docker Compose 管理，只能通过固定 Compose project、service、container ID 和项目 labels 证明归属，并使用 Compose 生命周期命令回收；不能把宿主 `docker-proxy` PID 当作普通项目进程终止。

默认端口：

- vLLM：`127.0.0.1:8001`
- 业务 API：`127.0.0.1:8000`
- 原版 UI：`127.0.0.1:3000`

捕获 `INT`、`TERM`、`HUP` 和正常退出。清理顺序为 UI、Worker、API、vLLM、按现有选项决定的 ES。vLLM 先 TERM，等待 30-60 秒，再只对已重新验证归属的 PGID 执行 KILL。成功标准优先检查登记的 PID/进程组消失和 compute 列表不再包含其成员，再比较 60 秒内显存是否恢复到启动前正负 1024 MiB。若期间出现新的未知 GPU 进程，结果标记为 inconclusive 或 cleanup failure，绝不误杀。

结构化证据分别保存 `primary_failure` 和 `cleanup_failures`，清理错误不得覆盖原始启动或业务故障。

## 14. vLLM 服务约束

vLLM 只监听 `127.0.0.1:8001`，served model 使用稳定别名 `qwen2.5-vl-local`。配置包括：

- 单卡、FP16 activation、eager mode、16K 上下文、单序列、16K batched-token 上限、24 图像硬上限和 200,704 pixels 单图上限。
- `limit_mm_per_prompt` 禁止原生 video 输入，只允许最多 24 张已经过本地抽取和缩放的 image；vLLM 0.8.5 使用 `--disable-mm-preprocessor-cache` 完全禁用多模态预处理缓存，避免形成未计算的内存副本。
- 禁止请求 body logging，关闭 Hugging Face、Transformers 和 vLLM telemetry。
- 模型路径指向已校验的本地 snapshot，不使用可变化的模型名称解析。
- 本地 adapter 配置只允许 loopback URL；非 loopback 配置验证失败。
- `/health`、`/v1/models` 和单帧 schema 探针都通过后才能启动业务组件。

首版命令参数基线为：

```text
--served-model-name qwen2.5-vl-local
--host 127.0.0.1
--port 8001
--tensor-parallel-size 1
--quantization awq
--dtype half
--max-model-len 16384
--max-num-seqs 1
--max-num-batched-tokens 16384
--gpu-memory-utilization 0.70
--limit-mm-per-prompt {"image":24,"video":0}
--mm-processor-kwargs {"min_pixels":3136,"max_pixels":200704}
--swap-space 0
--cpu-offload-gb 0
--disable-mm-preprocessor-cache
--enforce-eager
--disable-log-requests
```

参数是否受选定 vLLM 版本支持必须由 bootstrap probe 验证。任何参数变化都使容量校准失效，不能在日常启动时静默删除不支持的安全参数。

## 15. 本地分析与规范事件

本地 VLM 输出严格 schema，`extra='forbid'`。首版事件类型使用封闭枚举：

- `forklift_person_proximity`
- `ppe_missing`
- `restricted_zone_intrusion`
- `unsafe_vehicle_operation`
- `fall_or_person_down`
- `smoke_or_fire`
- `no_safety_event`
- `other_safety_event`

`object_categories`、`rule_tags`、PPE key/value、risk level 和 confidence bucket 都必须是封闭枚举并限制数量、长度和数值范围。`other_safety_event` 不能携带任意模型自由文本到远程；其本地证据只能留在本地。

模型输出非法 JSON 或 schema 不合法时只在本地重试一次，仍失败则片段明确失败，不把原始输出发送到远程 provider。

## 16. 全局远程出站边界

系统建立唯一 `RemoteProviderGateway`。DashScope LLM 和 embedding 的所有生产调用，包括 ingestion、query decomposition、embed search、critic、TopAgent、总结和重试，只能接受以下专用 DTO：

- `RemoteSafeIngestEvent`
- `RemoteSafeSearchQuery`
- `RemoteSafeSearchContext`
- `RemoteSafeConversationTurn`

禁止 gateway 接收任意 `str`、通用 `dict`、完整 `SearchResult`、本地 `UnderstandingResult` 或未投影的 message history。现有 adapter 的底层 HTTP 能力可以复用，但不得被业务代码绕过 gateway 直接调用。

DTO 采用封闭枚举、长度和数量上限、`extra='forbid'`，序列化后再次递归校验 key 和 value type。规范 embedding 文本只能由程序通过版本化枚举映射表生成，不得拼接 VLM `description`、`local_evidence` 或未知字段。

允许远程字段：

```text
event_type
relative start/end offset
object enum and bounded counts
risk enum and confidence bucket
rule enum
normalized PPE enum
opaque result_ref
通过本地敏感模式检查的用户查询
```

禁止远程字段：

```text
video path / filename / URL / Base64
sensor ID / camera ID / location
absolute timestamp
person identity / face / clothing free text
local_evidence / raw VLM output
本地 screenshot、thumbnail 或完整 search result
未知扩展字段
```

搜索 critic 和 TopAgent 只能看到安全事件与 opaque `result_ref`。远程回答返回后，本地 renderer 再用 `result_ref` 回填文件名、绝对时间、缩略图和播放地址；这些本地展示字段不得进入后续远程 conversation history。

用户查询不是天然安全。发送远程前执行本地敏感模式检查，至少识别路径、UUID、邮箱、电话、IP、摄像头编号、工号、绝对时间和明确位置标识。命中时首版默认拒绝远程调用并提示用户改写，同时保留仅本地关键词过滤路径。日志和 trace 只记录 query hash、长度和分类，不记录正文。

远程域名使用配置 allowlist；本地 VLM 只能访问 loopback，DashScope 只能访问批准的 API 域名。

## 17. 隐私投影与恢复语义

录播阶段增加持久化的 `PRIVACY_PROJECTING` 边界，或等价地持久化独立、带校验和的 remote projection artifact。远程 embedding 只能消费该 artifact，不能临时从 raw analysis 拼接字符串。

每个片段的检查点键至少包含：

```text
job_id + segment_id + source checksum
model revision + prompt version + vision schema version
privacy projection version + canonical mapping version
embedding model + dimensions
```

旧 privacy policy 或旧自由文本 embedding checkpoint 不得复用。策略版本变化时从投影阶段失效；视觉模型、源片段或提示版本变化时从本地分析阶段失效。

系统不承诺外部 provider 的 exactly-once。网络调用采用 at-least-once 加稳定幂等键（provider 支持时）；本地片段检查点减少重复 VLM 推理，但进程在模型返回和原子提交之间崩溃时允许安全重放。验收不得把“没有观察到重复”表述为严格 exactly-once。

## 18. 本地隐私生命周期

- 运行根目录和业务 data root 使用 `0700`，新建文件使用 `0600`，启动脚本设置 `umask 077`。
- 临时抽帧在对应 VLM 请求成功或失败后立即删除，不形成独立长期副本。
- 源视频、发布片段、缩略图、本地 raw VLM output 和 manifest 跟随 asset 生命周期；删除 asset 时级联删除本地文件、SQLite 状态和 Elasticsearch 文档。
- API、UI 和媒体服务首版只监听 loopback，通过 SSH 隧道访问；未来改为非 loopback 前必须增加认证和授权设计。
- vLLM 日志轮转并限制总大小；默认单文件 100 MiB、保留 5 个轮转文件，运行记录默认保留最近 20 次和 14 天内记录，取覆盖范围更大者，超期清理不得删除仍处于运行或失败调查标记的 run。
- 异常、第三方库日志和 trace 同样经过结构化 scrub，但隐私首先由不记录请求 body 和不传入敏感值保证，不能依赖正则补救。

## 19. 日志与运行证据

终端聚合日志使用组件前缀，完整日志写入本次 run。日志允许记录请求 ID、任务 ID、耗时、帧数、缩放尺寸、token 计数、模型指纹、资源快照、状态码和结构化错误类型。

日志禁止记录视频帧、Base64、完整路径、可识别文件名、原始 query、完整 VLM 输入输出、远程 payload 值和密钥。测试 observer 位于 gateway 序列化后、TLS 前，只在验收模式捕获无 Authorization 的请求体副本；产物权限为 0600，验证后自动删除。真实运行证据只保存 payload schema、key 列表、字节数和 HMAC/摘要，不保存值。

`runtime-evidence` 新增：

- 本地 VLM endpoint、served model、revision、量化和健康状态
- 启动前、warm-up 峰值、稳定状态和退出后的 GPU/RAM 快照
- 静态门槛、校准门槛、实际门槛和校准指纹
- 远程 gateway policy version 与允许 provider 域名
- 视觉 schema、隐私投影和 canonical mapping 版本
- 所有角色的真实 provider readiness，且不包含密钥或敏感业务值

## 20. 失败处理

- 本地 VLM 不可用：片段或任务失败，不回退远程视觉模型。
- DashScope LLM/embedding 不可用：保留本地分析和投影 checkpoint，只重试远程阶段。
- 隐私投影失败：禁止远程调用，保留本地故障证据。
- 资源不足、未知 GPU 进程、未知端口占用或身份不明：整栈启动失败。
- 任一必需组件启动失败：逆序停止本次已启动组件并保留本次 run。
- 模型、环境或校准指纹不匹配：日常启动失败，要求重新 bootstrap 或校准，不能在线自修复。

## 21. 测试与验收

### 21.1 本地自动化

资源和启动器测试覆盖：

- 动态显存公式、cgroup/RLIMIT 内存、分文件系统磁盘检查
- `nvidia-smi` 缺字段、`N/A`、低显存、高 utilization 和未知 compute process
- 三次 GPU 采样、GPU UUID 选择和初始化竞态
- PID 复用、boot ID 变化、旧 manifest、workload 握手 gate 和孤儿进程
- 未知端口监听、无法解析 PID、IPv4/IPv6 wildcard 和 bind 竞态
- `INT`、`TERM`、`HUP`、主失败与清理失败并存
- vLLM 停止超时、PGID 重验证和新未知 GPU 进程介入

隐私和业务测试覆盖：

- ingestion、decomposition、embedding、critic、TopAgent、history 和 retry 全部只能经过 gateway
- filename、path、sensor、absolute time、local evidence、free-text tag、query、history、tool result 分别注入唯一 canary
- canary 不出现在 LLM payload、embedding payload、日志、trace 或报告中
- 封闭枚举、`extra='forbid'`、递归序列化校验和 canonical mapping
- projection 前后、embedding 第 N 段、ES publish 前后的 crash 恢复
- 旧 privacy policy checkpoint 被拒绝
- 本地 VLM 非 loopback 配置 fail closed
- DashScope 故障不触发远程视觉回退，且本地结果不丢失
- asset 删除级联清除源视频、帧、缩略图、manifest、SQLite 和 ES 文档

### 21.2 Ubuntu 真实验收

1. bootstrap 首次成功、重复执行幂等、模型和依赖 manifest 可验证。
2. 日常启动处于离线模式，无模型下载或 revision 网络解析。
3. 当前服务器 preflight 输出 `total=24564 MiB`、动态 `required=21291 MiB`，并记录实际 free。
4. 本地 vLLM 单帧探针通过；24 张最大像素图像、最大文本和 1024 输出连续运行至少 3 次。
5. warm-up 无 OOM、无重启、无 Xid；GPU 空闲至少 4096 MiB，系统 `MemAvailable` 至少 16 GiB，新增 swap 不超过 256 MiB。
6. 连续处理至少 3 个真实业务视频任务，前端完成上传、状态轮询、搜索、播放和问答。
7. 使用无敏感数据调用真实 DashScope LLM 与 embedding；模型角色和 provider evidence 全部真实可用。
8. TLS 前测试 observer 证明全部 canary 未进入任何远程 payload，Authorization 从未写盘。
9. 模拟低资源、未知 GPU 进程和未知端口时正确拒绝，且目标进程始终存活。
10. 退出后登记进程组消失；无新未知进程介入时，60 秒内显存恢复到启动前正负 1024 MiB。
11. 所有组件日志可通过同一 run ID、job ID、segment ID 和 request ID 关联，且敏感值扫描通过。
12. 真实 asset 删除后，本地文件、SQLite、ES 和媒体访问全部完成级联清理。

首版性能门槛为无 OOM、可连续处理、可恢复和可观测。真实延迟与吞吐记录为后续优化基线，在取得实测数据前不承诺人为指定的 p95。

## 22. 并发实施边界

确认本文档后，实施可由三个独立代理并发：

1. 模型 bootstrap、容量计算、GPU/RAM/disk preflight 与校准。
2. 启动器锁、强进程归属、vLLM 生命周期、日志和清理。
3. 全局远程 gateway、隐私 DTO、版本化 projection 与片段 checkpoint。

主代理负责共享配置契约、集成、代码审查、全量测试、Ubuntu 同步与真实验收。三个分支在共享 DTO、manifest schema 和配置字段定稿后才能分别实现，避免产生多个可绕过的远程出口。

## 23. 完成定义

只有同时满足以下条件才能宣称本地 VLM 隐私改造完成：

- 官方模型与独立环境可重复准备且供应链身份固定。
- 每次启动执行动态资源准入，不误杀其他进程。
- 本地 VLM 经真实 24 帧压力验证且退出后释放资源。
- 业务链所有远程 LLM/embedding 调用都经过唯一 gateway。
- 全链路 canary 证明视频敏感数据没有离开服务器。
- 原版 UI 的真实上传、处理、搜索、播放和问答链路通过。
- 本地和 Ubuntu 测试、运行证据、清理证据完整。
- 代码合并到本地 `master`、推送远程，并在服务器 checkout 上完成最终验证。
