# 生产恢复验收编排实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each task must follow TDD: write a failing test, observe the failure, implement the minimum behavior, observe the pass, then commit.

**Goal:** 在 Ubuntu 无 sudo 环境中，用一个 Python 入口完成三个真实视频的并发上传、Worker 中断、完整栈重启、checkpoint 恢复、ES/搜索/媒体/删除验收，并生成可审计的中文报告。

**Architecture:** 新增一个只负责验收编排的 Python 模块和 CLI。它以子进程启动既有 `scripts/es-runtime-stack.sh`，不修改生产 API 或启动器的 Worker 自动重启行为；第一次栈退出后，以相同配置和数据根目录启动第二次栈。HTTP、SQLite、ES 和日志证据统一绑定 acceptance run，失败时只清理本次创建的资产和已验证归属的进程。

**Tech Stack:** Python 3.12+ 标准库、`httpx`、SQLite 只读连接、现有 FastAPI API、Elasticsearch HTTP API、`pytest`/`pytest-httpserver`、Ubuntu Bash。

## Global Constraints

- 服务器无管理员权限，不使用 sudo、systemctl 或杀死外部用户进程。
- 三个 `--video` 必须是三个存在、可读且内容 SHA-256 不同的真实文件。
- `--query` 只允许一个共享查询或三个按视频顺序绑定的查询。
- 生产 profile 必须 `allow_mock_fallback=false` 且 `force_mock_embedding=false`；真实 provider 失败不得降级。
- Worker PID 只允许来自本次 launcher 的 `processes.json`，并校验当前 UID、命令行、run ID 和 manifest 路径后才可 TERM。
- 日志不得包含 API key、Authorization、原始视频字节或完整模型图像请求；状态和报告使用原子写入。
- 不修改原版 UI 公共契约，不引入新的 NVIDIA/frontend 依赖，不同步根 Node 工具链实验文件。
- 每个任务结束前运行该任务列出的测试；服务器证据缺失时不得把报告写成 PASS。

---

### Task 1: 验收输入、状态与安全身份模型

**Files:**
- Create: `src/vsa_agent/recorded_video/production_acceptance.py`
- Create: `tests/unit/recorded_video/test_production_acceptance.py`

**Interfaces:**
- Produces `AcceptanceCase`, `JobIdentity`, `RunHandle`, `CheckpointEvidence` and `AcceptanceState` dataclasses.
- Produces `ValidationError(RuntimeError)` with `field: str` and `message: str` attributes.
- Produces `parse_cases(video_paths: Sequence[Path], queries: Sequence[str]) -> tuple[AcceptanceCase, ...]`.
- Produces `validate_worker_identity(manifest_path: Path, run_id: str, worker_pid: int, current_uid: int) -> None`.
- Produces `atomic_write_json(path: Path, payload: Mapping[str, object]) -> None`.

- [ ] **Step 1: 写失败测试**

```python
def test_parse_cases_requires_three_distinct_video_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    third = tmp_path / "three.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    third.write_bytes(b"one")

    with pytest.raises(ValueError, match="three distinct video files"):
        parse_cases([first, second, third], ["forklift"])
```

- [ ] **Step 2: 验证 RED**

Run: `pytest -q tests/unit/recorded_video/test_production_acceptance.py::test_parse_cases_requires_three_distinct_video_hashes`

Expected: FAIL because `parse_cases` does not yet exist.

- [ ] **Step 3: 实现最小模型**

`parse_cases` must resolve each path, require exactly three files, compute SHA-256 in 1 MiB chunks, reject duplicate resolved paths or hashes, and map one query to all cases or three queries positionally. `AcceptanceCase` stores only path, query, and digest; it never stores video bytes.

- [ ] **Step 4: 添加身份和状态测试并验证 GREEN**

Cover malformed JSON, non-atomic partial writes, foreign UID, mismatched run ID, wrong worker command, missing worker entry, and a valid manifest. Run: `pytest -q tests/unit/recorded_video/test_production_acceptance.py`.

- [ ] **Step 5: 提交**

```bash
git add src/vsa_agent/recorded_video/production_acceptance.py tests/unit/recorded_video/test_production_acceptance.py
git commit -m "test: define production acceptance identity contract"
```

### Task 2: 两次 launcher 生命周期与 Worker 中断

**Files:**
- Modify: `src/vsa_agent/recorded_video/production_acceptance.py`
- Modify: `tests/unit/recorded_video/test_production_acceptance.py`

**Interfaces:**
- `LauncherArgs` is a frozen dataclass containing `repo_root`, `api_port`, `es_port`, `ui_port`, `index`, `data_root`, `conda_env`, and `env`.
- Produces `LauncherController.start() -> RunHandle`.
- Produces `LauncherController.wait_ready(handle: RunHandle) -> RunHandle`.
- Produces `LauncherController.stop_worker(handle: RunHandle) -> None`.
- Produces `LauncherController.wait_exit(handle: RunHandle, timeout: float) -> int`.
- Produces `LauncherController.restart() -> RunHandle`, reusing the exact production arguments and data root.
- Test-only helpers are defined in the same test module with these signatures: `_fake_launcher_args(tmp_path: Path) -> LauncherArgs`, `_FakeProcessRunner`, and `write_manifest(path: Path, *, run_id: str, worker_pid: int) -> None`.

- [ ] **Step 1: 写失败测试**

```python
def test_controller_rejects_worker_pid_from_a_foreign_run(tmp_path: Path) -> None:
    controller = LauncherController(_fake_launcher_args(tmp_path), runner=_FakeProcessRunner())
    handle = RunHandle(run_id="run-a", run_dir=tmp_path / "run-a", process_pid=41)
    write_manifest(handle.run_dir / "processes.json", run_id="run-b", worker_pid=41)

    with pytest.raises(ValidationError, match="run ID"):
        controller.stop_worker(handle)
```

- [ ] **Step 2: 验证 RED**

Run: `pytest -q tests/unit/recorded_video/test_production_acceptance.py::test_controller_rejects_worker_pid_from_a_foreign_run`

Expected: FAIL because lifecycle control is not implemented.

- [ ] **Step 3: 实现最小 controller**

Use `subprocess.Popen` with `start_new_session=True` on Ubuntu, capture launcher output into the acceptance log, resolve `.runtime/es-stack/latest`, validate the UUID and `processes.json`, and send exactly one `signal.SIGTERM` to the verified worker supervisor PID. Do not use `pkill`, `killall`, shell interpolation, or PID-only matching.

- [ ] **Step 4: 验证 GREEN**

Fake the launcher with two UUID run directories and a worker process stub. Assert the first process exits nonzero after TERM, the second invocation keeps identical index/data-root/port arguments, the run IDs differ, and a foreign PID is never signaled. Run the focused unit test file.

- [ ] **Step 5: 提交**

```bash
git add src/vsa_agent/recorded_video/production_acceptance.py tests/unit/recorded_video/test_production_acceptance.py
git commit -m "feat: supervise two-run production acceptance lifecycle"
```

### Task 3: 三并发上传、checkpoint 基线与恢复对账

**Files:**
- Modify: `src/vsa_agent/recorded_video/production_acceptance.py`
- Modify: `tests/unit/recorded_video/test_production_acceptance.py`

**Interfaces:**
- Produces `ProductionApiClient.create_and_complete(case: AcceptanceCase) -> JobIdentity`.
- Produces `ProductionApiClient.wait_job(job: JobIdentity, timeout: float) -> JobSnapshot`.
- Produces `read_checkpoint_snapshot(database: Path, job_id: str) -> tuple[CheckpointEvidence, ...]` using `PRAGMA query_only=1`.
- Produces `assert_recovery(before: AcceptanceState, after: Mapping[str, JobSnapshot]) -> None`.
- Test-only `_state_with_three_jobs(tmp_path: Path, *, completed_stage: str, checksum: str, attempt: int = 1) -> AcceptanceState` is defined before the recovery tests and returns three jobs with deterministic segment IDs.

- [ ] **Step 1: 写失败测试**

```python
def test_recovery_preserves_completed_manifest_and_rejects_duplicate_segments(tmp_path: Path) -> None:
    before = _state_with_three_jobs(tmp_path, completed_stage="analyzing", checksum="sha-a")
    after = _state_with_three_jobs(tmp_path, completed_stage="analyzing", checksum="sha-a", attempt=2)
    after.segment_ids = ("segment-1", "segment-1")

    with pytest.raises(ValidationError, match="duplicate segment"):
        assert_recovery(before, after.jobs)
```

- [ ] **Step 2: 验证 RED**

Run: `pytest -q tests/unit/recorded_video/test_production_acceptance.py::test_recovery_preserves_completed_manifest_and_rejects_duplicate_segments`

Expected: FAIL because the recovery comparator does not exist.

- [ ] **Step 3: 实现最小并发与只读 checkpoint 查询**

Use `ThreadPoolExecutor(max_workers=3)` for the three upload/complete calls, retain all returned asset/job IDs, poll each status URL until `completed/publish`, and use SQLite read-only connections to capture stage, manifest, checksum, attempt, and elapsed fields. Allow attempt increments after restart, but require unchanged completed manifest/checksum and unique deterministic segment IDs.

- [ ] **Step 4: 验证 GREEN**

Cover one shared query, three positional queries, 202/200 identity mismatch, timeout, missing checkpoint, changed checksum, duplicate segment, and all-three completion. Run: `pytest -q tests/unit/recorded_video/test_production_acceptance.py`.

- [ ] **Step 5: 提交**

```bash
git add src/vsa_agent/recorded_video/production_acceptance.py tests/unit/recorded_video/test_production_acceptance.py
git commit -m "feat: verify concurrent jobs and checkpoint recovery"
```

### Task 4: ES、搜索、Range、删除与中文报告

**Files:**
- Modify: `src/vsa_agent/recorded_video/production_acceptance.py`
- Create: `scripts/recorded-video-production-acceptance.py`
- Modify: `tests/unit/recorded_video/test_production_acceptance.py`
- Modify: `tests/acceptance/test_recorded_video_validation_report.py`

**Interfaces:**
- Produces `collect_business_evidence(client, state) -> BusinessEvidence` for all three assets.
- Produces `render_acceptance_report(evidence: AcceptanceEvidence, report_path: Path) -> None`.
- `BusinessEvidence` and `AcceptanceEvidence` are frozen dataclasses defined in this task; test-only `_render_fixture_report(tmp_path: Path, *, asset_ids: tuple[str, ...], worker_restart: bool) -> str` renders a complete temporary report and is defined before the contract test.
- CLI accepts exactly three repeatable `--video`, one or three `--query`, `--config`, `--index`, `--data-root`, `--conda-env`, `--api-port`, `--es-port`, `--ui-port`, and `--report`.

- [ ] **Step 1: 写失败测试**

```python
def test_report_requires_three_assets_and_worker_restart_evidence(tmp_path: Path) -> None:
    report = _render_fixture_report(tmp_path, asset_ids=("asset-1", "asset-2", "asset-3"), worker_restart=False)

    with pytest.raises(AssertionError):
        _assert_complete_server_evidence(report)
```

- [ ] **Step 2: 验证 RED**

Run: `pytest -q tests/acceptance/test_recorded_video_validation_report.py::test_report_requires_three_assets_and_worker_restart_evidence`

Expected: FAIL because the report contract does not yet require the new fields.

- [ ] **Step 3: 实现证据收集和 CLI**

For each asset, refresh and query the configured ES index by asset/job identity, verify unique segment IDs and expected counts, call the same-origin search API, request the thumbnail, request `Range: bytes=0-0`, and delete twice while checking SQLite/ES/filesystem cleanup. Keep the existing primary `asset_id/job_id/segment_id` fields for compatibility, and add `asset_ids`, `job_ids`, `concurrency: 3`, `worker_restart: PASS`, `launcher_runs`, and `case_evidence_ref` fields. Render all seven report sections atomically and scan referenced logs for secrets before declaring PASS.

- [ ] **Step 4: 验证 GREEN**

Run the fake HTTP/ES suite, the full report contract suite, and `python scripts/recorded-video-production-acceptance.py --help`. Expected: all focused tests pass; malformed case counts and missing evidence return nonzero.

- [ ] **Step 5: 提交**

```bash
git add src/vsa_agent/recorded_video/production_acceptance.py scripts/recorded-video-production-acceptance.py tests/unit/recorded_video/test_production_acceptance.py tests/acceptance/test_recorded_video_validation_report.py
git commit -m "feat: add production recorded-video acceptance runner"
```

### Task 5: 同步、文档与 Ubuntu 真实 gate

**Files:**
- Modify: `scripts/sync-server-files.ps1`
- Modify: `docs/recorded-video-runtime.md`
- Modify: `docs/superpowers/reports/2026-07-13-production-recorded-video-validation.md`
- Modify: `openspec/changes/production-recorded-video-ingest/tasks.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Sync allowlist includes only the new acceptance script, production module, tests/docs needed on Ubuntu; it excludes root frontend Node manifests and `.runtime` artifacts.

- [ ] **Step 1: 写失败同步和文档测试**

```python
def test_sync_manifest_includes_acceptance_runner_without_root_node_manifests() -> None:
    text = Path("scripts/sync-server-files.ps1").read_text(encoding="utf-8")
    assert "scripts\\recorded-video-production-acceptance.py" in text
    assert '"frontend\\original-ui\\package-lock.json"' not in text
```

- [ ] **Step 2: 验证 RED**

Run: `pytest -q tests/unit/scripts/test_es_runtime_stack_script.py -k acceptance_runner`

Expected: FAIL until the allowlist and documentation command are added.

- [ ] **Step 3: 实现同步和运行文档**

Document the exact one-command invocation from the design, the required three real video inputs, the expected two launcher run directories, SSH tunnel, log paths, no-sudo constraint, and failure cleanup rules. Sync only the approved files to `Z:\vsa-agent` and hash-verify each file.

- [ ] **Step 4: 执行 Ubuntu gate**

After installing user-local Node/Playwright dependencies and confirming three real files exist, run the Playwright E2E command, then the production acceptance command with the real provider. Read the acceptance log/report from Z, verify `总体结果：PASS`, `三并发`, `Worker 重启`, HTTP 206, deletion cleanup, and no-key scan. Do not mark tasks complete on a partial command or a smoke-only result.

- [ ] **Step 5: 更新任务和提交**

Only after local and Ubuntu evidence pass, check off OpenSpec tasks 8.5, 9.2 and 9.4, update the development status/report, run `pytest -q`, frontend Jest/lint/typecheck, `npx openspec validate production-recorded-video-ingest --strict`, then commit the documentation/evidence changes.

### Task 6: Comet verify and integration handoff

- [ ] Run the final thorough review over the complete change, resolve Critical/Important findings, and record accepted Minor findings.
- [ ] Run the Comet build guard and transition to verify only after all tasks are checked and server evidence is present.
- [ ] Merge the branch into local `master`, push `master`, and archive the OpenSpec change only after final user confirmation.
- [ ] Keep selected-video Q&A outside this change; after this change is archived, start a separate `selected-recorded-video-chat` Comet change for asset/segment-bound chat context.
