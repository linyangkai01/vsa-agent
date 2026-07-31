#!/usr/bin/env python3
"""Offline model verification and fail-closed local-vLLM resource preflight."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - resource is available on the Ubuntu target
    resource = None  # type: ignore[assignment]

GIB = 1024**3
MIB = 1024**2
MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
MODEL_REVISION = "536a35794df8831aa814970ee8f89eff577e7718"
MODEL_REPOSITORY_BYTES = 6_939_964_850
MODEL_MANIFEST_SCHEMA = 1
VLLM_VERSION = "0.8.5"
TORCH_CUDA_PREFIX = "12.4"
TRANSFORMERS_VERSION = "4.51.3"
HUGGINGFACE_HUB_VERSION = "0.30.2"
COMPRESSED_TENSORS_VERSION = "0.9.3"
TORCH_VERSION = "2.6.0"
TORCHVISION_VERSION = "0.21.0"
TORCHAUDIO_VERSION = "2.6.0"
XFORMERS_VERSION = "0.0.29.post2"
PINNED_DISTRIBUTIONS = {
    "vllm": VLLM_VERSION,
    "torch": TORCH_VERSION,
    "torchvision": TORCHVISION_VERSION,
    "torchaudio": TORCHAUDIO_VERSION,
    "transformers": TRANSFORMERS_VERSION,
    "huggingface-hub": HUGGINGFACE_HUB_VERSION,
    "compressed-tensors": COMPRESSED_TENSORS_VERSION,
    "xformers": XFORMERS_VERSION,
}
GPU_MEMORY_UTILIZATION = 0.70
GPU_SAFETY_RESERVE_MIB = 4096
CALIBRATION_RESERVE_MIB = 2048
MAX_GPU_UTILIZATION_PCT = 10
GPU_SAMPLE_COUNT = 3
GPU_SAMPLE_INTERVAL_SEC = 1.0
DTYPE = "half"
QUANTIZATION = "awq"
MAX_MODEL_LEN = 16_384
MAX_NUM_SEQS = 1
MAX_NUM_BATCHED_TOKENS = 16_384
MAX_FRAMES = 24
MAX_IMAGE_PIXELS = 448 * 448
MIN_RAM_GIB = 24
WARN_RAM_GIB = 32
MIN_SHM_GIB = 1
MODEL_DISK_MIN_GIB = 10
RUNTIME_DISK_MIN_GIB = 15
VLM_PROMPT_VERSION = "recorded-video-prompt-v1"
VISION_SCHEMA_VERSION = "remote-egress-v1"
SAMPLING_POLICY_VERSION = "representative-frames-v1"

EXPECTED_MODEL_FILES: dict[str, int] = {
    ".gitattributes": 1_570,
    "LICENSE": 6_951,
    "README.md": 13_321,
    "added_tokens.json": 605,
    "chat_template.json": 1_049,
    "config.json": 1_415,
    "generation_config.json": 249,
    "merges.txt": 1_671_853,
    "model-00001-of-00002.safetensors": 3_982_163_944,
    "model-00002-of-00002.safetensors": 2_941_808_440,
    "model.safetensors.index.json": 89_593,
    "preprocessor_config.json": 575,
    "special_tokens_map.json": 613,
    "tokenizer.json": 11_422_063,
    "tokenizer_config.json": 5_776,
    "vocab.json": 2_776_833,
}
EXPECTED_SHA256 = {
    ".gitattributes": "34448b82c17d60fec9b65b1f093c115ddbaadc04beb1b0140b6bfed2e012a930",
    "LICENSE": "a64b31d02653e5354ae174101be2e97e221f57f53ed22a084b7df7e8364d018b",
    "README.md": "e674a38d66374a0b7f9053dbe15d496586820f66eb6ae016dc5d837e9f627941",
    "added_tokens.json": "58b54bbe36fc752f79a24a271ef66a0a0830054b4dfad94bde757d851968060b",
    "chat_template.json": "94174d7176c52a7192f96fc34eb2cf23c7c2059d63cdbfadca1586ba89731fb7",
    "config.json": "0ccd6378c18544511f59a2ffedb2a616974cd17b24f33ce9caaa40fdb53e187c",
    "generation_config.json": "c685cb6ca7485922d0c1778c30da8102e0fbeeda9d1fbe58fc19c327ac79ea8c",
    "merges.txt": "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
    "model-00001-of-00002.safetensors": "4f75e3de726546ee43620d1227d3596cd3ba0fdd19f11faeea71de578d2d1052",
    "model-00002-of-00002.safetensors": "dae4128bbfd2b8d489e838048edc0bbe6e31f269d9b96fa3effe11cc534b8f0c",
    "model.safetensors.index.json": "9bbb7f66770d7f0f3c2f880f257f991d0e6c756e0b2a86eedc37c7ad37d5581d",
    "preprocessor_config.json": "549c158011407dfb750d9ec578047cf76f5bfe365cd0aa069a50137d3f98d9dd",
    "special_tokens_map.json": "76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd",
    "tokenizer.json": "5eee858c5123a4279c3e1f7b81247343f356ac767940b2692a928ad929543214",
    "tokenizer_config.json": "0a6be425d5d62ec1904deb45e569c809d0973bd39a411452388f268a855e3183",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}


class PreflightError(RuntimeError):
    """An input or runtime condition cannot be verified safely."""


@dataclass(frozen=True)
class Check:
    component: str
    code: str
    ok: bool
    message: str
    details: dict[str, Any]


def _check(component: str, code: str, ok: bool, message: str, **details: Any) -> Check:
    return Check(component=component, code=code, ok=ok, message=message, details=details)


def sha256_file(path: Path, chunk_size: int = 8 * MIB) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_environment_fingerprint() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for distribution, expected in PINNED_DISTRIBUTIONS.items():
        try:
            actual = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise PreflightError(f"pinned runtime package is missing: {distribution}") from error
        if actual.split("+", 1)[0] != expected:
            raise PreflightError(
                f"runtime package version mismatch for {distribution}: expected {expected}, got {actual}"
            )
        versions[distribution] = actual
    try:
        import torch
    except ImportError as error:
        raise PreflightError("torch cannot be imported") from error
    cuda_runtime = torch.version.cuda or ""
    if not cuda_runtime.startswith(TORCH_CUDA_PREFIX):
        raise PreflightError(f"torch CUDA runtime mismatch: expected {TORCH_CUDA_PREFIX}, got {cuda_runtime or 'none'}")
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "packages": versions,
        "cuda_runtime": cuda_runtime,
    }


def build_environment_manifest() -> dict[str, Any]:
    runtime = runtime_environment_fingerprint()
    distributions: dict[str, dict[str, str]] = {}
    for name in PINNED_DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(name)
        record = distribution.read_text("RECORD")
        if not record:
            raise PreflightError(f"installed distribution has no RECORD metadata: {name}")
        distributions[name] = {
            "version": runtime["packages"][name],
            "record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
        }
    return {
        "schema_version": 1,
        "runtime": runtime,
        "distributions": distributions,
    }


def verify_environment_manifest(path: Path) -> dict[str, Any]:
    expected = load_json_object(path)
    actual = build_environment_manifest()
    if expected != actual:
        raise PreflightError("installed local-vLLM environment does not match its pinned manifest")
    return actual


def build_calibration_fingerprint(
    *,
    manifest_info: Mapping[str, Any],
    gpu: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    model_manifest_hash = hashlib.sha256(
        json.dumps(EXPECTED_SHA256, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_repository_bytes": manifest_info["repository_bytes"],
        "model_manifest_hash": model_manifest_hash,
        "model_config_hash": EXPECTED_SHA256["config.json"],
        "gpu_uuid": gpu["uuid"],
        "gpu_name": gpu["name"],
        "driver_version": gpu["driver_version"],
        "python": runtime["python"],
        "packages": runtime["packages"],
        "cuda_runtime": runtime["cuda_runtime"],
        "quantization": QUANTIZATION,
        "dtype": DTYPE,
        "kv_cache_dtype": "auto",
        "enforce_eager": True,
        "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
        "max_model_len": MAX_MODEL_LEN,
        "max_num_seqs": MAX_NUM_SEQS,
        "max_num_batched_tokens": MAX_NUM_BATCHED_TOKENS,
        "max_frames": MAX_FRAMES,
        "max_image_pixels": MAX_IMAGE_PIXELS,
        "limit_mm_per_prompt": {"image": MAX_FRAMES, "video": 0},
        "mm_processor_kwargs": {"min_pixels": 3136, "max_pixels": MAX_IMAGE_PIXELS},
        "prompt_version": VLM_PROMPT_VERSION,
        "vision_schema_version": VISION_SCHEMA_VERSION,
        "sampling_policy_version": SAMPLING_POLICY_VERSION,
    }


def build_model_manifest(snapshot_path: Path) -> dict[str, Any]:
    snapshot_path = snapshot_path.resolve(strict=True)
    actual_names = {path.name for path in snapshot_path.iterdir()}
    if actual_names != set(EXPECTED_MODEL_FILES):
        raise PreflightError("model snapshot file set does not match the pinned repository")
    files: dict[str, dict[str, Any]] = {}
    for relative_path, expected_size in EXPECTED_MODEL_FILES.items():
        path = snapshot_path / relative_path
        if not path.is_file():
            raise PreflightError(f"model file is missing: {relative_path}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise PreflightError(
                f"model file size mismatch for {relative_path}: expected {expected_size}, got {actual_size}"
            )
        actual_hash = sha256_file(path)
        expected_hash = EXPECTED_SHA256[relative_path]
        if actual_hash != expected_hash:
            raise PreflightError(f"model file hash mismatch for {relative_path}")
        files[relative_path] = {"size": actual_size, "sha256": actual_hash}
    return {
        "schema_version": MODEL_MANIFEST_SCHEMA,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "repository_bytes": MODEL_REPOSITORY_BYTES,
        "snapshot_path": str(snapshot_path),
        "files": files,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        try:
            Path(temporary_name).unlink()
        except OSError:
            pass
        raise


def _synthetic_png_data_url(width: int = 56, height: int = 56) -> str:
    import base64

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, level=9))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _http_json(url: str, *, payload: dict[str, Any] | None = None, timeout_sec: float = 30) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:  # noqa: S310 - loopback is enforced
            if response.status < 200 or response.status >= 300:
                raise PreflightError(f"local vLLM probe returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PreflightError(f"local vLLM probe failed: {type(error).__name__}") from error


def probe_vllm_service(base_url: str, served_model: str) -> dict[str, Any]:
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PreflightError("local vLLM probe endpoint must be loopback HTTP")
    root = base_url.rstrip("/")
    health_request = urllib.request.Request(f"{root}/health", method="GET")
    try:
        with urllib.request.urlopen(health_request, timeout=10) as response:  # noqa: S310 - loopback is enforced
            if response.status != 200:
                raise PreflightError(f"local vLLM health returned HTTP {response.status}")
    except (OSError, urllib.error.URLError) as error:
        raise PreflightError(f"local vLLM health probe failed: {type(error).__name__}") from error

    models = _http_json(f"{root}/v1/models", timeout_sec=10)
    model_ids = {
        item.get("id") for item in models.get("data", []) if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if served_model not in model_ids:
        raise PreflightError(f"served model alias is missing: {served_model}")
    completion = _http_json(
        f"{root}/v1/chat/completions",
        payload={
            "model": served_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Reply with the single word gray."},
                        {"type": "image_url", "image_url": {"url": _synthetic_png_data_url()}},
                    ],
                }
            ],
            "max_tokens": 8,
            "temperature": 0,
        },
        timeout_sec=180,
    )
    choices = completion.get("choices") if isinstance(completion, dict) else None
    if not isinstance(choices, list) or not choices:
        raise PreflightError("local vLLM single-frame probe returned no choices")
    return {"health": "ok", "served_model": served_model, "single_frame_probe": "ok"}


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"cannot read JSON file {path}: {type(error).__name__}") from error
    if not isinstance(payload, dict):
        raise PreflightError(f"JSON root must be an object: {path}")
    return payload


def verify_model_manifest(manifest_path: Path, *, full_hash: bool = True) -> dict[str, Any]:
    manifest = load_json_object(manifest_path)
    expected_metadata = {
        "schema_version": MODEL_MANIFEST_SCHEMA,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "repository_bytes": MODEL_REPOSITORY_BYTES,
    }
    for key, expected in expected_metadata.items():
        if manifest.get(key) != expected:
            raise PreflightError(f"model manifest {key} mismatch: expected {expected!r}")

    snapshot_value = manifest.get("snapshot_path")
    if not isinstance(snapshot_value, str) or not snapshot_value:
        raise PreflightError("model manifest snapshot_path is missing")
    snapshot_path = Path(snapshot_value).resolve(strict=True)
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(EXPECTED_MODEL_FILES):
        raise PreflightError("model manifest file set does not match the pinned repository")

    for relative_path, expected_size in EXPECTED_MODEL_FILES.items():
        entry = files.get(relative_path)
        if not isinstance(entry, dict) or entry.get("size") != expected_size:
            raise PreflightError(f"model manifest size mismatch for {relative_path}")
        recorded_hash = entry.get("sha256")
        if not isinstance(recorded_hash, str) or len(recorded_hash) != 64:
            raise PreflightError(f"model manifest hash is invalid for {relative_path}")
        expected_hash = EXPECTED_SHA256[relative_path]
        if recorded_hash != expected_hash:
            raise PreflightError(f"model manifest pinned hash mismatch for {relative_path}")
        model_file = snapshot_path / relative_path
        if not model_file.is_file() or model_file.stat().st_size != expected_size:
            raise PreflightError(f"offline model file is missing or truncated: {relative_path}")
        if full_hash and sha256_file(model_file) != recorded_hash:
            raise PreflightError(f"offline model file hash mismatch: {relative_path}")

    actual_names = {path.name for path in snapshot_path.iterdir()}
    if actual_names != set(EXPECTED_MODEL_FILES):
        raise PreflightError("offline model snapshot contains missing or extra files")

    return {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "snapshot_path": str(snapshot_path),
        "repository_bytes": MODEL_REPOSITORY_BYTES,
        "full_hash_verified": full_hash,
    }


def calculate_vram_requirement(
    total_mib: int,
    gpu_memory_utilization: float,
    *,
    safety_reserve_mib: int = 4096,
    measured_peak_delta_mib: int | None = None,
    calibration_reserve_mib: int = 2048,
) -> dict[str, int | float]:
    if total_mib <= 0:
        raise ValueError("total_mib must be positive")
    if not 0 < gpu_memory_utilization < 1:
        raise ValueError("gpu_memory_utilization must be between 0 and 1")
    if safety_reserve_mib < 0 or calibration_reserve_mib < 0:
        raise ValueError("VRAM reserves cannot be negative")
    engine_budget_mib = math.ceil(total_mib * gpu_memory_utilization)
    base_required_mib = engine_budget_mib + safety_reserve_mib
    calibrated_required_mib = 0
    if measured_peak_delta_mib is not None:
        if measured_peak_delta_mib < 0:
            raise ValueError("measured_peak_delta_mib cannot be negative")
        calibrated_required_mib = measured_peak_delta_mib + calibration_reserve_mib
    return {
        "total_mib": total_mib,
        "gpu_memory_utilization": gpu_memory_utilization,
        "engine_budget_mib": engine_budget_mib,
        "safety_reserve_mib": safety_reserve_mib,
        "calibrated_required_mib": calibrated_required_mib,
        "required_free_mib": max(base_required_mib, calibrated_required_mib),
    }


def parse_gpu_csv(text: str) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in csv.reader(line for line in text.splitlines() if line.strip()):
        if len(row) != 8:
            raise PreflightError(f"unexpected nvidia-smi GPU row with {len(row)} columns")
        try:
            samples.append(
                {
                    "index": int(row[0].strip()),
                    "name": row[1].strip(),
                    "uuid": row[2].strip(),
                    "total_mib": int(row[3].strip()),
                    "free_mib": int(row[4].strip()),
                    "used_mib": int(row[5].strip()),
                    "utilization_pct": int(row[6].strip()),
                    "driver_version": row[7].strip(),
                }
            )
        except ValueError as error:
            raise PreflightError("nvidia-smi returned a non-numeric GPU value") from error
    if not samples:
        raise PreflightError("nvidia-smi returned no GPU rows")
    return samples


def parse_compute_process_csv(text: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for row in csv.reader(line for line in text.splitlines() if line.strip()):
        if len(row) != 4:
            raise PreflightError(f"unexpected nvidia-smi process row with {len(row)} columns")
        try:
            pid = int(row[1].strip())
        except ValueError as error:
            raise PreflightError("nvidia-smi returned an invalid compute process PID") from error
        memory_text = row[3].strip()
        processes.append(
            {
                "gpu_uuid": row[0].strip(),
                "pid": pid,
                "process_name": row[2].strip(),
                "used_memory_mib": None if memory_text in {"", "N/A", "[N/A]"} else int(memory_text),
            }
        )
    return processes


def aggregate_gpu_samples(
    samples: Sequence[dict[str, Any]],
    gpu_index: int,
    *,
    expected_sample_count: int | None = None,
) -> dict[str, Any]:
    selected = [sample for sample in samples if sample["index"] == gpu_index]
    if not selected:
        raise PreflightError(f"GPU index {gpu_index} was not reported")
    if expected_sample_count is not None and len(selected) != expected_sample_count:
        raise PreflightError(
            f"GPU index {gpu_index} was reported {len(selected)} times; expected {expected_sample_count}"
        )
    identity = {
        (sample["name"], sample["uuid"], sample["total_mib"], sample.get("driver_version", "unknown"))
        for sample in selected
    }
    if len(identity) != 1:
        raise PreflightError("GPU identity changed during preflight sampling")
    name, uuid, total_mib, driver_version = identity.pop()
    return {
        "index": gpu_index,
        "name": name,
        "uuid": uuid,
        "total_mib": total_mib,
        "driver_version": driver_version,
        "sample_count": len(selected),
        "free_mib_samples": [sample["free_mib"] for sample in selected],
        "utilization_pct_samples": [sample["utilization_pct"] for sample in selected],
        "minimum_free_mib": min(sample["free_mib"] for sample in selected),
        "maximum_utilization_pct": max(sample["utilization_pct"] for sample in selected),
    }


def run_command(command: Sequence[str], timeout_sec: float = 10) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_sec)
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError(f"cannot execute {command[0]}: {type(error).__name__}") from error
    if completed.returncode != 0:
        raise PreflightError(f"{command[0]} exited with status {completed.returncode}")
    return completed.stdout


def sample_gpus(
    executable: str,
    *,
    sample_count: int = 3,
    interval_sec: float = 1.0,
    command_runner: Callable[[Sequence[str]], str] = run_command,
) -> list[dict[str, Any]]:
    if sample_count < 3:
        raise ValueError("GPU preflight requires at least three samples")
    query = [
        executable,
        "--query-gpu=index,name,uuid,memory.total,memory.free,memory.used,utilization.gpu,driver_version",
        "--format=csv,noheader,nounits",
    ]
    samples: list[dict[str, Any]] = []
    for sample_index in range(sample_count):
        current = parse_gpu_csv(command_runner(query))
        indices = [sample["index"] for sample in current]
        if len(indices) != len(set(indices)):
            raise PreflightError(f"nvidia-smi reported duplicate GPU rows in sample {sample_index + 1}")
        for sample in current:
            sample["sample_number"] = sample_index + 1
        samples.extend(current)
        if sample_index + 1 < sample_count and interval_sec > 0:
            time.sleep(interval_sec)
    return samples


def read_compute_processes(
    executable: str,
    command_runner: Callable[[Sequence[str]], str] = run_command,
) -> list[dict[str, Any]]:
    query = [
        executable,
        "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ]
    return parse_compute_process_csv(command_runner(query))


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        values[key] = value * multiplier
    if "MemAvailable" not in values:
        raise PreflightError("MemAvailable is missing from meminfo")
    return values


def resolve_cgroup_memory_root(cgroup_root: Path, membership_text: str) -> Path:
    for line in membership_text.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        hierarchy, controllers, relative_path = fields
        if hierarchy == "0" and controllers == "":
            candidate = cgroup_root / relative_path.lstrip("/")
            if candidate.is_dir():
                return candidate
        if "memory" in controllers.split(","):
            candidate = cgroup_root / "memory" / relative_path.lstrip("/")
            if candidate.is_dir():
                return candidate
    return cgroup_root


def _read_cgroup_available_bytes(cgroup_memory_root: Path, cgroup_root: Path | None = None) -> int | None:
    root = (cgroup_root or cgroup_memory_root).resolve()
    current = cgroup_memory_root.resolve()
    v2_candidates: list[int] = []
    while current == root or root in current.parents:
        v2_max = current / "memory.max"
        v2_current = current / "memory.current"
        if v2_max.is_file() and v2_current.is_file():
            maximum_text = v2_max.read_text(encoding="ascii").strip()
            if maximum_text != "max":
                v2_candidates.append(max(0, int(maximum_text) - int(v2_current.read_text(encoding="ascii").strip())))
        if current == root:
            break
        current = current.parent
    if v2_candidates:
        return min(v2_candidates)

    v1_max = cgroup_memory_root / "memory" / "memory.limit_in_bytes"
    v1_current = cgroup_memory_root / "memory" / "memory.usage_in_bytes"
    if (cgroup_memory_root / "memory.limit_in_bytes").is_file():
        v1_max = cgroup_memory_root / "memory.limit_in_bytes"
        v1_current = cgroup_memory_root / "memory.usage_in_bytes"
    if v1_max.is_file() and v1_current.is_file():
        maximum = int(v1_max.read_text(encoding="ascii").strip())
        current = int(v1_current.read_text(encoding="ascii").strip())
        if maximum >= 1 << 60:
            return None
        return max(0, maximum - current)
    return None


def calculate_effective_available_ram(
    mem_available_bytes: int,
    *,
    cgroup_available_bytes: int | None = None,
    rlimit_as_bytes: int | None = None,
) -> dict[str, int | None]:
    if mem_available_bytes < 0:
        raise ValueError("mem_available_bytes cannot be negative")
    candidates = [mem_available_bytes]
    if cgroup_available_bytes is not None:
        candidates.append(max(0, cgroup_available_bytes))
    if rlimit_as_bytes is not None:
        candidates.append(max(0, rlimit_as_bytes))
    return {
        "mem_available_bytes": mem_available_bytes,
        "cgroup_available_bytes": cgroup_available_bytes,
        "rlimit_as_bytes": rlimit_as_bytes,
        "effective_available_bytes": min(candidates),
    }


def _read_process_vmsize_bytes(proc_status_path: Path = Path("/proc/self/status")) -> int:
    try:
        for line in proc_status_path.read_text(encoding="ascii").splitlines():
            if line.startswith("VmSize:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * (1024 if len(parts) < 3 or parts[2].lower() == "kb" else 1)
    except OSError as error:
        raise PreflightError(f"cannot read process VmSize: {type(error).__name__}") from error
    raise PreflightError("VmSize is missing from process status")


def _read_rlimit_as_bytes(proc_status_path: Path = Path("/proc/self/status")) -> int | None:
    if resource is None:
        return None
    rlimit_soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    if rlimit_soft in {-1, resource.RLIM_INFINITY}:
        return None
    return max(0, int(rlimit_soft) - _read_process_vmsize_bytes(proc_status_path))


def inspect_memory(
    meminfo_path: Path,
    cgroup_root: Path,
    proc_self_cgroup_path: Path | None = None,
) -> dict[str, int | None]:
    try:
        meminfo = parse_meminfo(meminfo_path.read_text(encoding="ascii"))
        membership_text = ""
        if proc_self_cgroup_path is not None and proc_self_cgroup_path.is_file():
            membership_text = proc_self_cgroup_path.read_text(encoding="ascii")
        cgroup_memory_root = resolve_cgroup_memory_root(cgroup_root, membership_text)
        cgroup_available = _read_cgroup_available_bytes(cgroup_memory_root, cgroup_root)
        rlimit_available = _read_rlimit_as_bytes()
    except (OSError, ValueError) as error:
        raise PreflightError(f"cannot inspect effective memory: {type(error).__name__}") from error
    result = calculate_effective_available_ram(
        meminfo["MemAvailable"],
        cgroup_available_bytes=cgroup_available,
        rlimit_as_bytes=rlimit_available,
    )
    result["swap_total_bytes"] = meminfo.get("SwapTotal")
    result["swap_free_bytes"] = meminfo.get("SwapFree")
    return result


def inspect_shared_memory(path: Path = Path("/dev/shm"), minimum_bytes: int = MIN_SHM_GIB * GIB) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        usage = shutil.disk_usage(resolved)
    except OSError as error:
        raise PreflightError(f"cannot inspect shared memory: {type(error).__name__}") from error
    if not resolved.is_dir():
        raise PreflightError("shared memory path is not a directory")
    writable = os.access(resolved, os.W_OK | os.X_OK)
    return {
        "path": str(resolved),
        "free_bytes": usage.free,
        "required_bytes": minimum_bytes,
        "writable": writable,
        "ready": writable and usage.free >= minimum_bytes,
    }


def inspect_private_directory(
    path: Path,
    *,
    allow_readable_by_others: bool = True,
    require_writable: bool = True,
) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        stat_result = resolved.stat()
    except OSError as error:
        raise PreflightError(f"cannot inspect directory permissions: {type(error).__name__}") from error
    if not resolved.is_dir():
        raise PreflightError(f"required directory is not a directory: {resolved}")
    owner_ok = not hasattr(os, "getuid") or stat_result.st_uid == os.getuid()
    mode = stat_result.st_mode & 0o777
    private_enough = not bool(mode & 0o022) and (allow_readable_by_others or not bool(mode & 0o077))
    writable = os.access(resolved, os.W_OK | os.X_OK)
    return {
        "path": str(resolved),
        "owner_ok": owner_ok,
        "mode": f"{mode:03o}",
        "writable": writable,
        "ready": owner_ok and private_enough and (writable or not require_writable),
    }


def nearest_existing_ancestor(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PreflightError(f"no existing ancestor for disk path: {path}")
        candidate = parent
    return candidate


def inspect_disk_requirements(
    requirements: Sequence[tuple[str, Path, int]],
    disk_usage: Callable[[Path], shutil._ntuple_diskusage] = shutil.disk_usage,
) -> list[dict[str, Any]]:
    by_device: dict[int, dict[str, Any]] = {}
    for label, requested_path, required_bytes in requirements:
        existing_path = nearest_existing_ancestor(requested_path)
        try:
            device = existing_path.stat().st_dev
            free_bytes = disk_usage(existing_path).free
        except OSError as error:
            raise PreflightError(f"cannot inspect disk for {requested_path}: {type(error).__name__}") from error
        entry = by_device.setdefault(
            device,
            {
                "device": device,
                "probe_path": str(existing_path),
                "free_bytes": free_bytes,
                "required_bytes": 0,
                "labels": [],
                "paths": [],
            },
        )
        entry["free_bytes"] = min(entry["free_bytes"], free_bytes)
        entry["required_bytes"] = max(entry["required_bytes"], required_bytes)
        entry["labels"].append(label)
        entry["paths"].append(str(requested_path))
    return list(by_device.values())


def _load_calibration(
    path: Path | None,
    *,
    model_revision: str,
    gpu_uuid: str,
    gpu_memory_utilization: float,
    extra_fingerprint: dict[str, Any] | None = None,
) -> tuple[int | None, str, list[str]]:
    if path is None or not path.exists():
        return None, "absent", []
    calibration = load_json_object(path)
    fingerprint = calibration.get("fingerprint")
    if not isinstance(fingerprint, dict):
        raise PreflightError("calibration fingerprint is missing")
    expected = {
        "model_revision": model_revision,
        "gpu_uuid": gpu_uuid,
        "gpu_memory_utilization": gpu_memory_utilization,
    }
    expected.update(extra_fingerprint or {})
    peak = calibration.get("measured_peak_delta_mib")
    if not isinstance(peak, int) or peak < 0:
        raise PreflightError("calibration measured_peak_delta_mib is invalid")
    mismatches = [key for key, value in expected.items() if fingerprint.get(key) != value]
    if mismatches:
        return None, "stale", mismatches
    return peak, "valid", []


def _parse_disk_requirement(value: str) -> tuple[str, Path, int]:
    try:
        label, path_text, gib_text = value.rsplit("=", 2)
        required_gib = float(gib_text)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("disk requirement must be LABEL=PATH=MIN_GIB") from error
    if not label or not path_text or required_gib < 0:
        raise argparse.ArgumentTypeError("disk requirement must have a label, path, and non-negative MIN_GIB")
    return label, Path(path_text), math.ceil(required_gib * GIB)


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[Check] = []
    warnings: list[str] = []

    manifest_info = verify_model_manifest(args.model_manifest, full_hash=True)
    checks.append(
        _check(
            "model",
            "MODEL_OFFLINE_VERIFIED",
            True,
            "Pinned local model snapshot passed offline verification.",
            **manifest_info,
        )
    )
    environment_manifest = verify_environment_manifest(args.environment_manifest)
    runtime = environment_manifest["runtime"]
    checks.append(
        _check(
            "runtime_environment",
            "RUNTIME_ENVIRONMENT_PINNED",
            True,
            "Pinned local-vLLM runtime packages and CUDA runtime are present.",
            **runtime,
            manifest_path=str(args.environment_manifest.resolve()),
        )
    )

    raw_samples = sample_gpus(
        args.nvidia_smi,
        sample_count=GPU_SAMPLE_COUNT,
        interval_sec=GPU_SAMPLE_INTERVAL_SEC,
    )
    gpu = aggregate_gpu_samples(raw_samples, args.gpu_index, expected_sample_count=GPU_SAMPLE_COUNT)
    processes = [process for process in read_compute_processes(args.nvidia_smi) if process["gpu_uuid"] == gpu["uuid"]]
    unknown_processes = list(processes)
    checks.append(
        _check(
            "gpu_processes",
            "GPU_PROCESSES_CLEAR" if not unknown_processes else "UNKNOWN_GPU_PROCESS",
            not unknown_processes,
            "No unknown GPU compute process is present."
            if not unknown_processes
            else "Unknown GPU compute processes prevent a safe local-vLLM start.",
            processes=processes,
        )
    )

    calibration_fingerprint = build_calibration_fingerprint(
        manifest_info=manifest_info,
        gpu=gpu,
        runtime=runtime,
    )
    peak, calibration_status, calibration_mismatches = _load_calibration(
        args.calibration,
        model_revision=MODEL_REVISION,
        gpu_uuid=gpu["uuid"],
        gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
        extra_fingerprint={
            key: value
            for key, value in calibration_fingerprint.items()
            if key not in {"model_revision", "gpu_uuid", "gpu_memory_utilization"}
        },
    )
    if calibration_status == "stale":
        warnings.append(f"Calibration is stale and was ignored: {', '.join(calibration_mismatches)}")
    vram = calculate_vram_requirement(
        gpu["total_mib"],
        GPU_MEMORY_UTILIZATION,
        safety_reserve_mib=GPU_SAFETY_RESERVE_MIB,
        measured_peak_delta_mib=peak,
        calibration_reserve_mib=CALIBRATION_RESERVE_MIB,
    )
    enough_vram = gpu["minimum_free_mib"] >= vram["required_free_mib"]
    checks.append(
        _check(
            "gpu_memory",
            "GPU_MEMORY_READY" if enough_vram else "GPU_MEMORY_INSUFFICIENT",
            enough_vram,
            "GPU free memory satisfies the vLLM budget."
            if enough_vram
            else "GPU free memory is below the vLLM budget.",
            **gpu,
            **vram,
            deficit_mib=max(0, int(vram["required_free_mib"]) - gpu["minimum_free_mib"]),
            calibration_status=calibration_status,
        )
    )
    utilization_ok = gpu["maximum_utilization_pct"] <= MAX_GPU_UTILIZATION_PCT
    checks.append(
        _check(
            "gpu_utilization",
            "GPU_UTILIZATION_READY" if utilization_ok else "GPU_UTILIZATION_BUSY",
            utilization_ok,
            "GPU utilization is within the startup limit."
            if utilization_ok
            else "GPU utilization is above the startup limit.",
            maximum_utilization_pct=gpu["maximum_utilization_pct"],
            allowed_utilization_pct=MAX_GPU_UTILIZATION_PCT,
            samples=gpu["utilization_pct_samples"],
        )
    )

    memory = inspect_memory(args.meminfo, args.cgroup_root, args.proc_self_cgroup)
    required_ram_bytes = math.ceil(MIN_RAM_GIB * GIB)
    effective_ram = int(memory["effective_available_bytes"] or 0)
    enough_ram = effective_ram >= required_ram_bytes
    checks.append(
        _check(
            "system_memory",
            "SYSTEM_MEMORY_READY" if enough_ram else "SYSTEM_MEMORY_INSUFFICIENT",
            enough_ram,
            "Effective available RAM satisfies the local-vLLM budget."
            if enough_ram
            else "Effective available RAM is below the local-vLLM budget.",
            **memory,
            required_bytes=required_ram_bytes,
            deficit_bytes=max(0, required_ram_bytes - effective_ram),
        )
    )
    if enough_ram and effective_ram < math.ceil(WARN_RAM_GIB * GIB):
        warnings.append(f"Effective available RAM is below the recommended {WARN_RAM_GIB:g} GiB.")

    shared_memory = inspect_shared_memory(args.shm)
    checks.append(
        _check(
            "shared_memory",
            "SHARED_MEMORY_READY" if shared_memory["ready"] else "SHARED_MEMORY_INSUFFICIENT",
            bool(shared_memory["ready"]),
            "Shared memory is writable and satisfies the runtime budget."
            if shared_memory["ready"]
            else "Shared memory is unavailable, read-only, or below the runtime budget.",
            **shared_memory,
        )
    )

    for label, path, require_writable, allow_readable in (
        ("model", Path(manifest_info["snapshot_path"]), False, True),
        ("runtime", args.output.parent, True, False),
    ):
        permissions = inspect_private_directory(
            path,
            require_writable=require_writable,
            allow_readable_by_others=allow_readable,
        )
        checks.append(
            _check(
                "directory_permissions",
                "DIRECTORY_PERMISSIONS_READY" if permissions["ready"] else "DIRECTORY_PERMISSIONS_UNSAFE",
                bool(permissions["ready"]),
                f"{label} directory ownership and permissions are acceptable."
                if permissions["ready"]
                else f"{label} directory ownership or permissions are unsafe.",
                label=label,
                **permissions,
            )
        )

    disk_requirements = [
        ("model", Path(manifest_info["snapshot_path"]), math.ceil(MODEL_DISK_MIN_GIB * GIB)),
        ("runtime", args.output.parent, math.ceil(RUNTIME_DISK_MIN_GIB * GIB)),
        *args.disk_requirement,
    ]
    disk_filesystems = inspect_disk_requirements(disk_requirements)
    for filesystem in disk_filesystems:
        enough_disk = filesystem["free_bytes"] >= filesystem["required_bytes"]
        checks.append(
            _check(
                "disk",
                "DISK_READY" if enough_disk else "DISK_INSUFFICIENT",
                enough_disk,
                "Filesystem free space satisfies its runtime budget."
                if enough_disk
                else "Filesystem free space is below its runtime budget.",
                **filesystem,
                deficit_bytes=max(0, filesystem["required_bytes"] - filesystem["free_bytes"]),
            )
        )

    ok = all(check.ok for check in checks)
    return {
        "schema_version": 1,
        "ok": ok,
        "status": "pass" if ok else "fail",
        "checks": [asdict(check) for check in checks],
        "warnings": warnings,
        "model": manifest_info,
        "gpu": gpu,
        "calibration_fingerprint": calibration_fingerprint,
        "runtime": runtime,
    }


def _preflight_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("preflight", help="Run fail-closed local-vLLM capacity checks.")
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--environment-manifest", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--nvidia-smi", default="nvidia-smi")
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    parser.add_argument("--proc-self-cgroup", type=Path, default=Path("/proc/self/cgroup"))
    parser.add_argument("--shm", type=Path, default=Path("/dev/shm"))
    parser.add_argument(
        "--disk-requirement",
        type=_parse_disk_requirement,
        action="append",
        default=[],
        metavar="LABEL=PATH=MIN_GIB",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.set_defaults(command="preflight")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("model-manifest", help="Build the pinned model manifest.")
    manifest_parser.add_argument("--snapshot", type=Path, required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)
    manifest_parser.set_defaults(command="model-manifest")
    verify_parser = subparsers.add_parser("verify-model", help="Verify the pinned model without network access.")
    verify_parser.add_argument("--model-manifest", type=Path, required=True)
    verify_parser.set_defaults(command="verify-model")
    environment_manifest_parser = subparsers.add_parser(
        "environment-manifest", help="Write the pinned installed-package manifest."
    )
    environment_manifest_parser.add_argument("--output", type=Path, required=True)
    environment_manifest_parser.set_defaults(command="environment-manifest")
    verify_environment_parser = subparsers.add_parser(
        "verify-environment", help="Verify the installed packages against their pinned manifest."
    )
    verify_environment_parser.add_argument("--manifest", type=Path, required=True)
    verify_environment_parser.set_defaults(command="verify-environment")
    probe_parser = subparsers.add_parser("probe-service", help="Probe local vLLM health, alias, and vision input.")
    probe_parser.add_argument("--base-url", required=True)
    probe_parser.add_argument("--served-model", required=True)
    probe_parser.set_defaults(command="probe-service")
    _preflight_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "model-manifest":
            payload = build_model_manifest(args.snapshot)
            write_json_atomic(args.output, payload)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "verify-model":
            payload = verify_model_manifest(args.model_manifest, full_hash=True)
            print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "environment-manifest":
            payload = build_environment_manifest()
            write_json_atomic(args.output, payload)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "verify-environment":
            payload = verify_environment_manifest(args.manifest)
            print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "probe-service":
            payload = probe_vllm_service(args.base_url, args.served_model)
            print(json.dumps({"ok": True, **payload}, ensure_ascii=False, sort_keys=True))
            return 0
        payload = run_preflight(args)
        write_json_atomic(args.output, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["ok"] else 1
    except (PreflightError, OSError, ValueError) as error:
        payload = {
            "schema_version": 1,
            "ok": False,
            "status": "error",
            "error": {"type": type(error).__name__, "message": str(error)},
        }
        if getattr(args, "output", None):
            try:
                write_json_atomic(args.output, payload)
            except OSError:
                pass
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
