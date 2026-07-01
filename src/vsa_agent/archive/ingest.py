from __future__ import annotations

import json
import re
from pathlib import Path

from vsa_agent.archive.index import upsert_archive_records
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.archive.models import build_record_id

KNOWN_TAGS = (
    "person",
    "worker",
    "pedestrian",
    "forklift",
    "vehicle",
    "truck",
    "safety",
    "loading",
    "warehouse",
)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Required manifest.json not found in live run directory: {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _first_sentence(text: str, fallback: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return fallback
    parts = re.split(r"(?<=[.!?])\s+", compact)
    return parts[0][:500]


def _extract_tags(text: str) -> list[str]:
    lowered = text.lower()
    return [tag for tag in KNOWN_TAGS if tag in lowered]


def build_record_from_live_run(run_dir: str | Path) -> ArchiveRecord:
    path = Path(run_dir)
    manifest = _load_manifest(path)
    qa_text = _read_text(path / "qa-final.txt")
    report_text = _read_text(path / "report-final.txt")

    video_path = str(manifest.get("video_path", ""))
    video_name = Path(video_path).name or "unknown-video"
    sensor_id = Path(video_name).stem or video_name
    run_id = str(manifest.get("run_id") or path.name)
    search_text = "\n\n".join(
        part for part in [qa_text, report_text, json.dumps(manifest, ensure_ascii=False)] if part
    )

    return ArchiveRecord(
        record_id=build_record_id(run_id, video_path),
        video_name=video_name,
        video_path=video_path,
        description=_first_sentence(qa_text or report_text, fallback=video_name),
        search_text=search_text,
        start_time=str(manifest.get("started_at", "")),
        end_time=str(manifest.get("ended_at", "")),
        sensor_id=sensor_id,
        screenshot_url="",
        object_ids=_extract_tags(search_text),
        metadata={
            "run_dir": str(path),
            "mode": manifest.get("mode", ""),
            "llm_model": manifest.get("llm_model", ""),
            "vlm_model": manifest.get("vlm_model", ""),
            "qa_status": (manifest.get("qa") or {}).get("status", ""),
            "report_status": (manifest.get("report") or {}).get("status", ""),
            "manifest_path": str(path / "manifest.json"),
            "qa_path": str(path / "qa-final.txt") if (path / "qa-final.txt").exists() else "",
            "report_path": str(path / "report-final.txt") if (path / "report-final.txt").exists() else "",
        },
    )


def ingest_live_run(run_dir: str | Path, index_path: str | Path) -> ArchiveRecord:
    record = build_record_from_live_run(run_dir)
    upsert_archive_records(index_path, [record])
    return record
