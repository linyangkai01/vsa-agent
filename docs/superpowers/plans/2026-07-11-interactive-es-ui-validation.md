---
change: script-es-runtime-stack
design-doc: docs/superpowers/specs/2026-07-06-script-es-runtime-stack-design.md
base-ref: a20786b41a8827781dda08846866c1eeb7d0e999
archived-with: 2026-07-12-script-es-runtime-stack
---

# ES 原版前端交互验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一个默认持续运行的一键脚本，启动 Elasticsearch、FastAPI 与原版 VSS UI，并让 VSS Search 的输入通过 `/api/v1/search -> SearchAgent -> embed_search -> Elasticsearch` 返回可见结果。

**Architecture:** 以现有 `SearchInput` 作为浏览器请求的严格输入契约，在新的 API router 中转为仓库真实存在的 `SearchAgentInput` 并调用 `execute_search`（仓库中不存在设计文字所称的 `execute_search_agent`）。启动器继续只生成 `.runtime/es-stack/config.yaml`，但在启动任何组件前接管指定的三个端口；完成 API 路由烟测后启动原版 UI，并保留本次拥有的 API/UI 子进程直至 `Ctrl+C`。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、现有 SearchAgent/ToolRegistry、Elasticsearch Docker Compose、PowerShell、bash、Node/npm/Turbo、pytest。

## Global Constraints

- 开发必须遵循 Comet；本计划属于 OpenSpec change `script-es-runtime-stack`。
- 已提交的 `config.yaml` 必须继续保持 `search.enabled: false`；只向子进程传入 `.runtime/es-stack/config.yaml` 的 `VSA_CONFIG`。
- `search.force_mock_embedding` 默认必须为 `false`；仅快速验证生成的临时配置将其设为 `true`，使 ingest 与浏览器查询使用相同确定性向量。
- 不实现原版 NVIDIA 的 Kafka、Logstash、VST 或 MDX 服务，不写入视频字节，不新增独立前端页面、前端 ES 客户端或平行搜索算法。
- 仅检查、记录并终止用户指定的 `EsPort`、`ApiPort`、`UiPort` 的监听者；不得扫描或终止其它端口。
- 正常单元测试不得启动 Docker、Elasticsearch、浏览器或真实模型服务。
- Windows 启动器使用 `taskkill /T /F` 清理自己启动的 API/UI 进程树；Linux 启动器使用 `setsid` 和进程组；两者在默认退出时均不停止 ES，只有显式 `StopElasticsearch` 才停止它。
- 本地验证完成后，使用显式清单同步到 `Z:\vsa-agent`，再在 Ubuntu 服务器执行真实运行验证；不要把映射盘同步当成服务器验证成功。

archived-with: 2026-07-12-script-es-runtime-stack
---

## File Structure

- Create `src/vsa_agent/api/original_ui_search.py`: 原版 VSS `POST /api/v1/search` adapter；输入为现有 `SearchInput`，输出为现有 `SearchOutput`。
- Modify `src/vsa_agent/api/routes.py`: 挂载上述 router。
- Modify `src/vsa_agent/agents/search_agent.py`: 在已有 `write_live_trace_event("search_agent.embed_search", ...)` 同时写入 API 日志，便于浏览器验收时检索。
- Modify `src/vsa_agent/config.py` and `src/vsa_agent/tools/embed_search.py`: 增加并消费仅用于快速验证的 `force_mock_embedding` 开关。
- Create `tests/unit/api/test_original_ui_search_route.py`: 不启动 ES 的路由契约、SearchAgent 调用和 app 注册测试。
- Modify `tests/unit/agents/test_search_agent.py`: 覆盖 embed-only 路径会记录 `search_agent.embed_search`。
- Modify `tests/unit/test_config_search.py` and `tests/unit/tools/test_embed_search.py`: 覆盖开关默认关闭及开启时跳过真实 embedding 客户端。
- Modify `scripts/es_ingest_smoke.py` and `tests/unit/scripts/test_es_ingest_smoke.py`: 写入与 mock query embedding 维度一致的样例向量，并经新 API 搜索验证 `{data: [...]}`。
- Modify `scripts/es-runtime-stack.ps1`, `scripts/es-runtime-stack.sh`, and `tests/unit/scripts/test_es_runtime_stack_script.py`: 添加 UI 端口、端口接管、UI 子进程、就绪检查、持续交互模式和仅 smoke 退出模式。
- Modify `docs/superpowers/reference/es-video-search-runtime.md`, `docs/DEVELOPMENT_STATUS.md`, and `scripts/sync-server-files.ps1`: 记录操作方式、浏览器证据、同步新增文件和当前状态。

### Task 1: 定义原版 VSS 搜索 API 契约

**Files:**
- Create: `tests/unit/api/test_original_ui_search_route.py`
- Create: `src/vsa_agent/api/original_ui_search.py`
- Modify: `src/vsa_agent/api/routes.py`
- Modify: `tests/unit/agents/test_search_agent.py`
- Modify: `src/vsa_agent/agents/search_agent.py`

**Interfaces:**
- Consumes: `SearchInput(query, source_type, video_sources, timestamp_start, timestamp_end, top_k, min_cosine_similarity, agent_mode)` from `src/vsa_agent/tools/search.py`.
- Produces: `POST /api/v1/search` with response `SearchOutput` serialized as `{"data": [SearchResult, ...]}`.
- Calls: `execute_search(search_input: SearchAgentInput) -> SearchOutput` from `src/vsa_agent/agents/search_agent.py`; it resolves registered `embed_search` through `ToolRegistry` and emits `search_agent.embed_search` in the embed-only path.

- [x] **Step 1: 写入会失败的路由测试**

```python
# tests/unit/api/test_original_ui_search_route.py
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_vss_search_preserves_request_and_response_contract(monkeypatch):
    from vsa_agent.api import original_ui_search
    from vsa_agent.tools.search import SearchOutput, SearchResult

    captured = {}

    async def fake_execute_search(*, search_input):
        captured["input"] = search_input
        return SearchOutput(data=[SearchResult(
            video_name="runtime-validation.mp4", description="forklift passes near worker",
            start_time="2026-07-04T08:00:00Z", end_time="2026-07-04T08:00:05Z",
            sensor_id="camera-runtime-1", screenshot_url="", similarity=0.91,
        )])

    monkeypatch.setattr(original_ui_search, "execute_search", fake_execute_search)
    app = FastAPI()
    app.include_router(original_ui_search.router)
    client = TestClient(app)
    response = client.post("/api/v1/search", json={
        "query": "forklift near worker", "top_k": 3, "source_type": "video_file",
        "video_sources": [], "timestamp_start": None, "timestamp_end": None,
        "min_cosine_similarity": "0.00", "agent_mode": False,
    })

    assert response.status_code == 200
    assert response.json()["data"][0]["video_name"] == "runtime-validation.mp4"
    assert captured["input"].query == "forklift near worker"
    assert captured["input"].top_k == 3
    assert captured["input"].max_results == 3
    assert captured["input"].agent_mode is False


def test_vss_search_route_is_registered_on_application():
    from vsa_agent.api.routes import app
    assert "/api/v1/search" in {route.path for route in app.routes}
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/api/test_original_ui_search_route.py -q`

Expected: FAIL，提示 `vsa_agent.api.original_ui_search` 尚不存在。

- [x] **Step 3: 实现最小 adapter 并挂载 router**

```python
# src/vsa_agent/api/original_ui_search.py
import logging

from fastapi import APIRouter

from vsa_agent.agents.search_agent import SearchAgentInput
from vsa_agent.agents.search_agent import execute_search
from vsa_agent.tools.search import SearchInput
from vsa_agent.tools.search import SearchOutput

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchOutput)
async def original_ui_search(request: SearchInput) -> SearchOutput:
    top_k = request.top_k or 10
    logger.info("original_ui.search.request query=%r top_k=%d agent_mode=%s", request.query, top_k, request.agent_mode)
    return await execute_search(SearchAgentInput(
        query=request.query, source_type=request.source_type, top_k=top_k,
        max_results=top_k, agent_mode=request.agent_mode, use_critic=request.use_critic,
    ))
```

Add `from vsa_agent.api.original_ui_search import router as original_ui_search_router` and `app.router.routes.extend(original_ui_search_router.routes)` beside the existing ingest router setup. In each existing `search_agent.embed_search` success/error trace branch, add a matching `logger.info("search_agent.embed_search path=%s query=%r", path, query)` before returning so `api.log` contains the event name without logging credentials or whole result payloads.

- [x] **Step 4: 运行路由与 agent 回归测试**

Run: `python -m pytest tests/unit/api/test_original_ui_search_route.py tests/unit/api/test_video_search_ingest.py tests/unit/agents/test_search_agent.py -q`

Expected: PASS；路由测试证明原版 `data.data` 消费契约与 agent 参数转换没有回归。

- [x] **Step 5: 提交该可测试单元**

```powershell
git add src/vsa_agent/api/original_ui_search.py src/vsa_agent/api/routes.py src/vsa_agent/agents/search_agent.py tests/unit/api/test_original_ui_search_route.py tests/unit/agents/test_search_agent.py
git commit -m "feat: expose original UI search through search agent"
```

### Task 2: 将运行 smoke 扩展为 API 搜索链路验证

**Files:**
- Modify: `scripts/es_ingest_smoke.py`
- Modify: `tests/unit/scripts/test_es_ingest_smoke.py`

**Interfaces:**
- Consumes: `/api/search/ingest`，以及 Task 1 的 `/api/v1/search`。
- Produces: `post_original_ui_search(api_url, query, top_k, timeout_sec) -> dict[str, Any]`；成功输出仍包含 `PASS: Elasticsearch ingest and search smoke validation`。

- [x] **Step 1: 增加失败测试，先固定新请求和向量维度**

```python
def test_post_original_ui_search_posts_vss_contract(monkeypatch):
    from scripts.es_ingest_smoke import post_original_ui_search
    # 复用现有 FakeResponse；fake_urlopen 捕获 full_url、method 和 JSON body。
    monkeypatch.setattr("scripts.es_ingest_smoke.urlopen", fake_urlopen)
    post_original_ui_search("http://127.0.0.1:8000", "forklift near worker", 1, 7.5)
    assert captured["url"] == "http://127.0.0.1:8000/api/v1/search"
    assert captured["body"] == {"query": "forklift near worker", "top_k": 1, "source_type": "video_file", "agent_mode": False}
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/scripts/test_es_ingest_smoke.py -q`

Expected: FAIL，缺少 `post_original_ui_search`。

- [x] **Step 3: 实现 API 搜索 smoke**

在 `scripts/es_ingest_smoke.py` 添加下列纯函数，并在 `_run` 的 ingest、直接 ES `multi_match` 验证之后调用它：

```python
def mock_query_vector(query: str) -> list[float]:
    seed = sum(ord(char) for char in query) % 1000
    return [seed * 0.001, seed * 0.002, seed * 0.003, (seed % 100) * 0.01]


def post_original_ui_search(api_url: str, query: str, top_k: int, timeout_sec: float) -> dict[str, Any]:
    request = Request(f"{api_url.rstrip('/')}/api/v1/search", data=json.dumps({
        "query": query, "top_k": top_k, "source_type": "video_file", "agent_mode": False,
    }).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"Expected {{'data': [...]}} from /api/v1/search, got: {payload!r}")
    return payload
```

Change `sample_payload(video_id, vector)` to receive `mock_query_vector(args.search_query)` and add `--search-query` default `forklift near worker`. This gives the ingested document the same four dimensions as the mock embed search query; retain the direct ES document and keyword-search assertions, then require the route response to contain the sample `video_name`. Do not call a remote embedding service in this script.

- [x] **Step 4: 运行 smoke 单元测试**

Run: `python -m pytest tests/unit/scripts/test_es_ingest_smoke.py -q`

Expected: PASS；所有请求都被 fake `urlopen`/fake ES 捕获，未启动 Docker。

- [x] **Step 5: 提交该可测试单元**

```powershell
git add scripts/es_ingest_smoke.py tests/unit/scripts/test_es_ingest_smoke.py
git commit -m "test: verify original UI search API in ES smoke"
```

### Task 3: 实现跨平台交互式全栈启动器与端口接管

**Files:**
- Modify: `tests/unit/scripts/test_es_runtime_stack_script.py`
- Modify: `scripts/es-runtime-stack.ps1`
- Modify: `scripts/es-runtime-stack.sh`

**Interfaces:**
- Consumes: `ApiPort=8000`, `EsPort=9200`, new `UiPort=3000`, `CondaEnv`, `TimeoutSec`, `StopElasticsearch` and existing `run_original_ui_vss.sh`。
- Produces: 默认交互式运行；`-SmokeOnly` / `--smoke-only` 为 CI 保留验证后退出路径；UI 使用 `NEXT_PUBLIC_ENABLE_SEARCH_TAB=true`、`NEXT_PUBLIC_AGENT_API_URL_BASE=http://127.0.0.1:<ApiPort>/api/v1` 与 `PORT=<UiPort>`。

- [x] **Step 1: 先扩展离线脚本契约测试**

```python
def test_windows_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _script_text()
    for required in ("[int]$UiPort = 3000", "Get-NetTCPConnection", "Win32_Process",
                     "Wait-PortFree", "taskkill.exe", "run_original_ui_vss.sh",
                     "NEXT_PUBLIC_ENABLE_SEARCH_TAB", "NEXT_PUBLIC_AGENT_API_URL_BASE",
                     "$uiProcess", "SmokeOnly"):
        assert required in text


def test_linux_stack_reclaims_selected_ports_and_starts_original_ui():
    text = _bash_script_text()
    for required in ("--ui-port", "--smoke-only", "port_listener_pids", "kill -TERM",
                     "wait_for_port_free", "run_original_ui_vss.sh", "UI_PID",
                     "NEXT_PUBLIC_ENABLE_SEARCH_TAB", "NEXT_PUBLIC_AGENT_API_URL_BASE"):
        assert required in text
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/scripts/test_es_runtime_stack_script.py -q`

Expected: FAIL，因为两份启动器还没有 UI、端口接管或 smoke-only 接口。

- [x] **Step 3: 实现 PowerShell 生命周期**

在参数中加入 `[int]$UiPort = 3000` 和 `[switch]$SmokeOnly`。以以下 helper 替换仅检测 `$ApiPort` 的逻辑，并在调用 `es-dev-start.ps1` 前依次对 `$EsPort,$ApiPort,$UiPort` 执行：

```powershell
function Reclaim-Port {
    param([int]$Port, [int]$TimeoutSec)
    $owners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($pid in $owners) {
        $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue).CommandLine
        Write-Host "Reclaiming port $Port from PID $pid: $command"
        & taskkill.exe /PID $pid /T /F | Out-Null
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (@(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0) {
        if ((Get-Date) -ge $deadline) { throw "Port $Port was not released within $TimeoutSec seconds" }
        Start-Sleep -Milliseconds 500
    }
}
```

新增 `$uiProcess`、`ui.log`、`ui.err.log`、`Wait-HttpReachable`；使用临时环境变量启动 `bash scripts/run_original_ui_vss.sh`，传入 `PORT=$UiPort` 与三个 `NEXT_PUBLIC_*` 值。API health、ingest/API search smoke、UI HTTP 探测均成功后打印 UI/API/ES/index/log 路径。若非 `SmokeOnly`，运行 `Wait-Process -Id $uiProcess.Id`；在 `finally` 对 `$uiProcess` 和 `$apiProcess` 调用现有 `Stop-OwnedProcessTree`，仅在 `StopElasticsearch` 时调用 `es-dev-stop.ps1`，随后恢复父 shell 环境变量。

- [x] **Step 4: 实现 bash 生命周期**

加入 `UI_PORT=3000`、`SMOKE_ONLY=0`、`UI_PID=""` 和参数解析。实现 `port_listener_pids`（优先 `lsof -ti TCP:$1 -sTCP:LISTEN`，退回 `fuser -n tcp`/`ss`）、`reclaim_port`（打印 `pid` 与 `ps -p "$pid" -o args=`，先 `kill -TERM`，超时后 `kill -KILL`，调用 `wait_for_port_free`）、`wait_http_reachable`。在所有三个端口释放后才运行 `docker compose`，并用下列环境启动独立 UI 进程组：

```bash
NEXT_PUBLIC_ENABLE_SEARCH_TAB=true \
NEXT_PUBLIC_AGENT_API_URL_BASE="${API_URL}/api/v1" \
NEXT_PUBLIC_HTTP_CHAT_COMPLETION_URL="${API_URL}/chat/stream" \
PORT="$UI_PORT" \
setsid bash "$SCRIPT_DIR/run_original_ui_vss.sh" >"$UI_LOG_PATH" 2>"$UI_ERR_LOG_PATH" &
UI_PID=$!
```

`cleanup` 必须仅终止非空的 `API_PID`/`UI_PID` 进程组，打印四个日志路径，并保留现有 `STOP_ELASTICSEARCH` 行为。`SMOKE_ONLY=1` 时在 smoke 后正常退出；默认等待 UI PID，使 `Ctrl+C` 触发 trap。

- [x] **Step 5: 运行静态、语法与焦点测试**

Run:

```powershell
python -m pytest tests/unit/scripts/test_es_runtime_stack_script.py tests/unit/scripts/test_es_ingest_smoke.py -q
powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw scripts\es-runtime-stack.ps1)); 'PASS'"
bash -n scripts/es-runtime-stack.sh
```

Expected: pytest 全部 PASS；两个语法检查均打印/返回成功。若当前 Windows shell 的 bash 不能创建信号管道，只记录该精确环境限制，Ubuntu 必须补跑 `bash -n`。

- [x] **Step 6: 提交该可测试单元**

```powershell
git add scripts/es-runtime-stack.ps1 scripts/es-runtime-stack.sh tests/unit/scripts/test_es_runtime_stack_script.py
git commit -m "feat: run interactive ES API and original UI stack"
```

### Task 4: 文档、同步和真实浏览器验收

**Files:**
- Modify: `docs/superpowers/reference/es-video-search-runtime.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `scripts/sync-server-files.ps1`
- Modify: `openspec/changes/script-es-runtime-stack/tasks.md`
- Modify: `openspec/changes/script-es-runtime-stack/.comet.yaml`
- Create: `docs/superpowers/reports/2026-07-11-interactive-es-ui-validation.md`

**Interfaces:**
- Consumes: Tasks 1-3 的脚本、API、单元测试。
- Produces: Windows/Ubuntu 命令、浏览器证据步骤、精确同步 manifest 与包含成功或阻塞证据的验证报告。

- [x] **Step 1: 先写出文档验收清单**

在运行文档新增以下命令和验收项：

```bash
cd /data/project/lyk/vsa-agent
./scripts/es-runtime-stack.sh --api-port 8000 --es-port 9200 --ui-port 3000 --index vsa-video-embeddings --conda-env vsa-agent
```

浏览器打开 `http://127.0.0.1:3000`，进入已启用的 Search 页，输入 `forklift near worker`，确认结果中出现 `runtime-validation.mp4`。同一时间在 `.runtime/es-stack/api.log` 找到 `original_ui.search.request` 和 `search_agent.embed_search`，并使用 `curl http://127.0.0.1:9200/vsa-video-embeddings/_search` 确认索引记录。说明 `Ctrl+C` 只清理本次 API/UI，`--stop-elasticsearch` 才停止 ES，且三个指定端口上已有进程会被终止且不会恢复。

- [x] **Step 2: 更新同步清单与状态**

在 `IncludePaths` 加入：

```text
src\vsa_agent\api\original_ui_search.py
src\vsa_agent\api\routes.py
src\vsa_agent\agents\search_agent.py
tests\unit\api\test_original_ui_search_route.py
tests\unit\agents\test_search_agent.py
tests\unit\scripts\test_es_ingest_smoke.py
docs\superpowers\plans\2026-07-11-interactive-es-ui-validation.md
docs\superpowers\reports\2026-07-11-interactive-es-ui-validation.md
```

更新状态文件：目标改为“交互式 ES/API/UI 与原版 VSS Search 验证”，下一条服务器命令改为本任务命令。仅在单元、OpenSpec、服务器浏览器验收都已有证据后勾选 `tasks.md` 的 5.1-5.3。

- [x] **Step 3: 本地验证、同步与服务器验证**

Run:

```powershell
python -m pytest tests/unit/api/test_original_ui_search_route.py tests/unit/api/test_video_search_ingest.py tests/unit/agents/test_search_agent.py tests/unit/tools/test_embed_search.py tests/unit/scripts/test_es_ingest_smoke.py tests/unit/scripts/test_es_runtime_stack_script.py -q
npx openspec validate script-es-runtime-stack
.\scripts\sync-server-files.ps1 -PreflightOnly
.\scripts\sync-server-files.ps1
```

Expected: 测试与 OpenSpec PASS，sync 输出每个显式文件。随后在服务器运行 Step 1 命令，收集浏览器结果、`api.log` 两个事件和 ES `_search` 的输出写入报告；Docker、conda、Node 或权限失败必须逐字记录为 BLOCKED，不能标记通过。

- [x] **Step 4: 提交验证资料**

```powershell
git add docs/superpowers/reference/es-video-search-runtime.md docs/DEVELOPMENT_STATUS.md scripts/sync-server-files.ps1 openspec/changes/script-es-runtime-stack/tasks.md openspec/changes/script-es-runtime-stack/.comet.yaml docs/superpowers/reports/2026-07-11-interactive-es-ui-validation.md
git commit -m "docs: record interactive ES UI validation"
```

## Self-Review

- Spec coverage: Task 1 implements原版 `/api/v1/search` 与 `{data: [...]}` 契约，并经真实 SearchAgent 的注册 `embed_search` 路径执行；Task 2 将该链路加入可重复 smoke；Task 3 覆盖三端口接管、UI 环境、健康检查、持续运行和仅清理拥有进程；Task 4 覆盖文档、显式同步、浏览器/API/ES 三重证据及 Comet/OpenSpec 收尾。
- Placeholder scan: 已检查计划不存在未决占位内容或无具体测试的泛化步骤；每项代码改动提供了精确文件、接口、测试样例、命令与预期结果。
- Type consistency: API 输入始终为 `SearchInput`，adapter 产生 `SearchAgentInput`，agent 返回 `SearchOutput`，前端消费 `data: SearchResult[]`；脚本使用同一 `ApiPort`/`EsPort`/`UiPort` 生成 URL、环境变量和日志路径。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-11-interactive-es-ui-validation.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

## 后续修复任务：验证数据与构建日志

### Task 5: 幂等的验证数据

**Files:**
- Modify: `src/vsa_agent/api/video_search_ingest.py`
- Modify: `scripts/es_ingest_smoke.py`
- Modify: `tests/unit/api/test_video_search_ingest.py`
- Modify: `tests/unit/scripts/test_es_ingest_smoke.py`

- [x] 先在 API 单元测试中断言 `AsyncElasticsearch.index()` 接收 `id="video-1"`；在 smoke 参数测试中断言默认 `--video-id` 为 `runtime-validation-video`。
- [x] 运行两个聚焦测试，确认现有实现分别因缺少 `id` 参数和时间戳默认 ID 而失败。
- [x] 在 ingest API 调用中传入 `id=request.video_id`；将 smoke 默认 ID 改为 `runtime-validation-video`，并在写入前仅删除视频名、传感器和 `runtime-yard` 元数据均匹配的历史验证文档。
- [x] 运行 `python -m pytest tests/unit/api/test_video_search_ingest.py tests/unit/scripts/test_es_ingest_smoke.py -q`。
- [x] 提交：`fix: keep ES smoke validation idempotent`。

### Task 6: 清理失效声明源映射

**Files:**
- Modify: `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/map/lib-src/server.d.ts`
- Modify: `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/dashboard/lib-src/server.d.ts`
- Modify: `frontend/original-ui/packages/nv-metropolis-bp-vss-ui/alerts/lib-src/server.d.ts`
- Modify: `scripts/sync-server-files.ps1`
- Modify: `tests/unit/scripts/test_es_runtime_stack_script.py`

- [x] 先添加静态测试，要求三个文件都不包含 `sourceMappingURL=server.d.ts.map`，且同步清单包含三个文件。
- [x] 运行聚焦测试，确认其因现有陈旧引用和缺失同步清单失败。
- [x] 只删除三个 `sourceMappingURL` 注释，并将三个声明文件加入定向同步清单。
- [x] 运行 `python -m pytest tests/unit/scripts/test_es_runtime_stack_script.py -q`；在服务器上重启运行栈，确认 UI 日志不再出现 `failed to read input source map`。
- [x] 提交：`fix: remove stale original UI declaration source maps`。
