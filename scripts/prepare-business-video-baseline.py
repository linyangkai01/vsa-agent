#!/usr/bin/env python3
"""Prepare the external real business-video regression dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from vsa_agent.recorded_video.business_preparation import (  # noqa: E402
    DatasetPreparationError,
    prepare_business_dataset,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download, verify, and derive the real business-video baseline.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/business_video_baseline/manifest.yaml"),
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--no-download", action="store_true", help="Require all source videos to be preseeded.")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        prepared = prepare_business_dataset(
            args.manifest,
            args.data_root,
            download_missing=not args.no_download,
            ffmpeg_path=args.ffmpeg,
            ffprobe_path=args.ffprobe,
        )
    except (DatasetPreparationError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("PASS: real business-video dataset prepared")
    print(f"  dataset: {prepared.manifest.dataset_id}@{prepared.manifest.dataset_version}")
    print(f"  sources: {len(prepared.source_paths)}")
    print(f"  cases: {len(prepared.clip_paths)}")
    print(f"  resolved manifest: {prepared.resolved_manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
