from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest


def _production_acceptance_module():
    try:
        return importlib.import_module("vsa_agent.recorded_video.production_acceptance")
    except ModuleNotFoundError:
        pytest.fail("production acceptance module does not exist")


def test_parse_cases_requires_three_distinct_video_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    third = tmp_path / "three.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    third.write_bytes(b"one")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="three distinct video files"):
        module.parse_cases([first, second, third], ["forklift"])


def test_parse_cases_maps_one_query_to_three_distinct_videos(tmp_path: Path) -> None:
    videos = []
    for index, suffix in enumerate((".mp4", ".mp4", ".mkv"), start=1):
        path = tmp_path / f"case-{index}{suffix}"
        path.write_bytes(f"video-{index}".encode())
        videos.append(path)

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, ["forklift near worker"])

    assert [case.path for case in cases] == [path.resolve() for path in videos]
    assert [case.query for case in cases] == ["forklift near worker"] * 3
    assert len({case.sha256 for case in cases}) == 3


def test_parse_cases_maps_three_queries_positionally(tmp_path: Path) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)
    queries = ["forklift", "worker fall", "smoke"]

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, queries)

    assert [case.query for case in cases] == queries


@pytest.mark.parametrize("queries", ([], ["one", "two"], ["  "]))
def test_parse_cases_rejects_invalid_query_cardinality_or_blanks(tmp_path: Path, queries: list[str]) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="one or three non-empty queries"):
        module.parse_cases(videos, queries)


def test_parse_cases_rejects_non_file_inputs_with_stable_error(tmp_path: Path) -> None:
    directory = tmp_path / "directory.mp4"
    directory.mkdir()
    second = tmp_path / "second.mp4"
    third = tmp_path / "third.mkv"
    second.write_bytes(b"second")
    third.write_bytes(b"third")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="regular readable video files"):
        module.parse_cases([directory, second, third], ["forklift"])


def test_validation_error_exposes_field_and_message() -> None:
    module = _production_acceptance_module()

    error = module.ValidationError("worker_identity", "worker manifest is invalid")

    assert str(error) == "worker manifest is invalid"
    assert error.field == "worker_identity"
    assert error.message == "worker manifest is invalid"


def test_atomic_write_json_replaces_existing_file_without_leaving_temporary_files(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    target = tmp_path / "acceptance-state.json"
    target.write_text('{"state":"old"}\n', encoding="utf-8")

    module.atomic_write_json(target, {"state": "ready", "jobs": ["job-1"]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "ready", "jobs": ["job-1"]}
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_atomic_write_json_preserves_previous_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _production_acceptance_module()
    target = tmp_path / "acceptance-state.json"
    target.write_text('{"state":"old"}\n', encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace denied")

    monkeypatch.setattr(module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace denied"):
        module.atomic_write_json(target, {"state": "new"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "old"}
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def _write_worker_manifest(path: Path, *, run_id: str, worker_pid: int, command: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "processes": [
                    {
                        "component": "worker",
                        "pid": worker_pid,
                        "command": command or "python scripts/recorded-video-worker.py --config <runtime-config>",
                        "started_at": "2026-07-21T00:00:00Z",
                        "exit_status": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_fake_proc(
    proc_root: Path,
    *,
    run_dir: Path,
    worker_pid: int,
    uid: int,
    command: list[str] | None = None,
) -> None:
    process_dir = proc_root / str(worker_pid)
    process_dir.mkdir(parents=True)
    (process_dir / "status").write_text(
        f"Name:\tpython\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )
    arguments = command or [
        "python",
        str(Path("scripts") / "runtime-log-supervisor.py"),
        "--label",
        "worker",
        "--stack-log",
        str(run_dir / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        str(Path("scripts") / "recorded-video-worker.py"),
        "--config",
        str(run_dir / "config.yaml"),
    ]
    (process_dir / "cmdline").write_bytes(b"\0".join(os.fsencode(item) for item in arguments) + b"\0")


def test_validate_worker_identity_rejects_malformed_manifest(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    manifest.parent.mkdir()
    manifest.write_text("{not-json", encoding="utf-8")

    with pytest.raises(module.ValidationError, match="JSON") as raised:
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")

    assert raised.value.field == "worker_identity"


def test_validate_worker_identity_rejects_foreign_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    _write_worker_manifest(manifest, run_id="run-b", worker_pid=101)

    with pytest.raises(module.ValidationError, match="run ID"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")


def test_validate_worker_identity_requires_one_active_worker(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    manifest = tmp_path / "run-a" / "processes.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"run_id": "run-a", "processes": []}), encoding="utf-8")

    with pytest.raises(module.ValidationError, match="one active worker"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=tmp_path / "proc")


def test_validate_worker_identity_rejects_foreign_uid(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=2000)

    with pytest.raises(module.ValidationError, match="current UID"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_wrong_worker_command(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101, command="python unrelated.py")
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000)

    with pytest.raises(module.ValidationError, match="worker command"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_log_path_from_another_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    command = [
        "python",
        "scripts/runtime-log-supervisor.py",
        "--stack-log",
        str(tmp_path / "run-b" / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        "scripts/recorded-video-worker.py",
        "--config",
        str(run_dir / "config.yaml"),
    ]
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000, command=command)

    with pytest.raises(module.ValidationError, match="stack log path"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_rejects_config_from_another_run(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    command = [
        "python",
        "scripts/runtime-log-supervisor.py",
        "--stack-log",
        str(run_dir / "stack.log"),
        "--component-log",
        str(run_dir / "worker.log"),
        "--status-file",
        str(run_dir / "worker.status.json"),
        "--component",
        "worker",
        "--",
        "python",
        "scripts/recorded-video-worker.py",
        "--config",
        str(tmp_path / "run-b" / "config.yaml"),
    ]
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000, command=command)

    with pytest.raises(module.ValidationError, match="runtime config path"):
        module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)


def test_validate_worker_identity_accepts_bound_worker_supervisor(tmp_path: Path) -> None:
    module = _production_acceptance_module()
    run_dir = tmp_path / "run-a"
    manifest = run_dir / "processes.json"
    proc_root = tmp_path / "proc"
    _write_worker_manifest(manifest, run_id="run-a", worker_pid=101)
    _write_fake_proc(proc_root, run_dir=run_dir, worker_pid=101, uid=1000)

    module.validate_worker_identity(manifest, "run-a", 101, 1000, proc_root=proc_root)
