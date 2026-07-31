from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/local_vllm_runtime.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("local_vllm_runtime", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vram_budget_uses_total_fraction_and_calibration_max():
    runtime = _load_module()

    base = runtime.calculate_vram_requirement(24_564, 0.70)
    calibrated = runtime.calculate_vram_requirement(24_564, 0.70, measured_peak_delta_mib=20_000)

    assert base["engine_budget_mib"] == 17_195
    assert base["required_free_mib"] == 21_291
    assert calibrated["calibrated_required_mib"] == 22_048
    assert calibrated["required_free_mib"] == 22_048


def test_gpu_samples_use_minimum_free_and_maximum_utilization():
    runtime = _load_module()
    rows = [
        {
            "index": 0,
            "name": "RTX 4090 D",
            "uuid": "GPU-1",
            "total_mib": 24_564,
            "free_mib": free,
            "utilization_pct": util,
        }
        for free, util in [(24_211, 0), (23_900, 4), (24_000, 2)]
    ]

    aggregate = runtime.aggregate_gpu_samples(rows, 0)

    assert aggregate["sample_count"] == 3
    assert aggregate["minimum_free_mib"] == 23_900
    assert aggregate["maximum_utilization_pct"] == 4


def test_gpu_csv_and_unknown_compute_process_parsing():
    runtime = _load_module()

    gpu = runtime.parse_gpu_csv("0, NVIDIA GeForce RTX 4090 D, GPU-1, 24564, 24211, 1, 0, 550.163.01\n")
    processes = runtime.parse_compute_process_csv("GPU-1, 1234, python, 2048\n")

    assert gpu[0]["free_mib"] == 24_211
    assert gpu[0]["driver_version"] == "550.163.01"
    assert processes == [{"gpu_uuid": "GPU-1", "pid": 1234, "process_name": "python", "used_memory_mib": 2048}]


def test_gpu_sampling_requires_three_observations():
    runtime = _load_module()

    with pytest.raises(ValueError, match="at least three"):
        runtime.sample_gpus("nvidia-smi", sample_count=2, interval_sec=0, command_runner=lambda _command: "")


def test_effective_ram_is_minimum_of_host_cgroup_and_rlimit():
    runtime = _load_module()

    result = runtime.calculate_effective_available_ram(
        58 * runtime.GIB,
        cgroup_available_bytes=30 * runtime.GIB,
        rlimit_as_bytes=26 * runtime.GIB,
    )

    assert result["effective_available_bytes"] == 26 * runtime.GIB


def test_meminfo_and_cgroup_v2_are_combined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime = _load_module()
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 41943040 kB\nSwapTotal: 8388608 kB\nSwapFree: 7340032 kB\n")
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(32 * runtime.GIB))
    (cgroup / "memory.current").write_text(str(4 * runtime.GIB))
    monkeypatch.setattr(runtime, "_read_rlimit_as_bytes", lambda: None)

    result = runtime.inspect_memory(meminfo, cgroup)

    assert result["mem_available_bytes"] == 40 * runtime.GIB
    assert result["cgroup_available_bytes"] == 28 * runtime.GIB
    assert result["effective_available_bytes"] == 28 * runtime.GIB


def test_cgroup_membership_selects_the_current_v2_subtree(tmp_path: Path):
    runtime = _load_module()
    current = tmp_path / "user.slice" / "session.scope"
    current.mkdir(parents=True)

    selected = runtime.resolve_cgroup_memory_root(tmp_path, "0::/user.slice/session.scope\n")

    assert selected == current


def test_cgroup_available_uses_the_tightest_parent_limit(tmp_path: Path):
    runtime = _load_module()
    parent = tmp_path / "user.slice"
    current = parent / "session.scope"
    current.mkdir(parents=True)
    (tmp_path / "memory.max").write_text("max")
    (tmp_path / "memory.current").write_text("0")
    (parent / "memory.max").write_text(str(30 * runtime.GIB))
    (parent / "memory.current").write_text(str(4 * runtime.GIB))
    (current / "memory.max").write_text(str(40 * runtime.GIB))
    (current / "memory.current").write_text(str(2 * runtime.GIB))

    assert runtime._read_cgroup_available_bytes(current, tmp_path) == 26 * runtime.GIB


def test_rlimit_headroom_subtracts_current_virtual_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime = _load_module()
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmSize:\t4194304 kB\n")

    class FakeResource:
        RLIMIT_AS = 1
        RLIM_INFINITY = -1

        @staticmethod
        def getrlimit(_kind):
            return 10 * runtime.GIB, 10 * runtime.GIB

    monkeypatch.setattr(runtime, "resource", FakeResource)

    assert runtime._read_rlimit_as_bytes(status) == 6 * runtime.GIB


def test_gpu_sampling_rejects_duplicate_rows_in_one_observation():
    runtime = _load_module()
    row = "0, RTX 4090 D, GPU-1, 24564, 24211, 1, 0, 550.163.01\n"

    with pytest.raises(runtime.PreflightError, match="duplicate GPU rows"):
        runtime.sample_gpus(
            "nvidia-smi",
            sample_count=3,
            interval_sec=0,
            command_runner=lambda _command: row + row,
        )


def test_disk_requirements_are_checked_per_filesystem_and_coalesced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime = _load_module()
    model = tmp_path / "model"
    run = tmp_path / "run"
    model.mkdir()
    run.mkdir()

    def fake_usage(_path):
        return runtime.shutil._ntuple_diskusage(100, 80, 20)

    results = runtime.inspect_disk_requirements(
        [("model", model, 10), ("runtime", run, 15)],
        disk_usage=fake_usage,
    )

    assert len(results) == 1
    assert results[0]["required_bytes"] == 15
    assert set(results[0]["labels"]) == {"model", "runtime"}


def test_stale_calibration_is_ignored_but_malformed_calibration_fails(tmp_path: Path):
    runtime = _load_module()
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "fingerprint": {
                    "model_revision": runtime.MODEL_REVISION,
                    "gpu_uuid": "different",
                    "gpu_memory_utilization": 0.70,
                },
                "measured_peak_delta_mib": 18_000,
            }
        )
    )

    peak, status, mismatches = runtime._load_calibration(
        path,
        model_revision=runtime.MODEL_REVISION,
        gpu_uuid="GPU-1",
        gpu_memory_utilization=0.70,
    )

    assert peak is None
    assert status == "stale"
    assert mismatches == ["gpu_uuid"]

    path.write_text(json.dumps({"fingerprint": {}}))
    with pytest.raises(runtime.PreflightError, match="measured_peak"):
        runtime._load_calibration(
            path,
            model_revision=runtime.MODEL_REVISION,
            gpu_uuid="GPU-1",
            gpu_memory_utilization=0.70,
        )


def test_manifest_rejects_unpinned_revision_without_reading_model(tmp_path: Path):
    runtime = _load_module()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_id": runtime.MODEL_ID,
                "revision": "main",
                "repository_bytes": runtime.MODEL_REPOSITORY_BYTES,
                "snapshot_path": str(tmp_path),
                "files": {},
            }
        )
    )

    with pytest.raises(runtime.PreflightError, match="revision mismatch"):
        runtime.verify_model_manifest(manifest)


def test_cli_writes_structured_error_and_exits_nonzero(tmp_path: Path):
    runtime = _load_module()
    output = tmp_path / "preflight.json"

    exit_code = runtime.main(
        [
            "preflight",
            "--model-manifest",
            str(tmp_path / "missing.json"),
            "--environment-manifest",
            str(tmp_path / "environment-manifest.json"),
            "--calibration",
            str(tmp_path / "calibration.json"),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text())
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert "Traceback" not in payload["error"]["message"]


def test_preflight_cli_has_no_policy_weakening_switches():
    runtime = _load_module()
    help_text = runtime.build_parser().format_help()
    preflight = runtime.build_parser()._subparsers._group_actions[0].choices["preflight"]
    option_strings = {option for action in preflight._actions for option in action.option_strings}

    assert "--allow-compute-pid" not in option_strings
    assert "--skip-model-hash" not in option_strings
    assert "--gpu-memory-utilization" not in option_strings
    assert "preflight" in help_text


def test_synthetic_probe_image_is_a_real_png_and_remote_endpoint_is_rejected():
    runtime = _load_module()
    data_url = runtime._synthetic_png_data_url()

    assert data_url.startswith("data:image/png;base64,iVBORw0KGgo")
    with pytest.raises(runtime.PreflightError, match="loopback"):
        runtime.probe_vllm_service("https://example.com", "qwen2.5-vl-local")
