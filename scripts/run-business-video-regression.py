#!/usr/bin/env python3
"""Run the real-provider business-video regression against a started stack."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from vsa_agent.recorded_video.business_regression import (  # noqa: E402
    BusinessRegressionOptions,
    run_business_regression,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real business-video accuracy regression.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/business_video_baseline/manifest.yaml"),
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", choices=("quick", "release", "full"), default="quick")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-url", default="http://127.0.0.1:3000")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".runtime/business-video-regression"),
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--request-attempts", type=int, default=3)
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        options = BusinessRegressionOptions(
            manifest=args.manifest,
            data_root=args.data_root,
            profile=args.profile,
            api_url=args.api_url,
            ui_url=args.ui_url,
            output_root=args.output_root,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            request_attempts=args.request_attempts,
            run_id=args.run_id,
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    exit_code = run_business_regression(options)
    run_id = args.run_id or "latest generated run"
    if exit_code == 0:
        print(f"PASS: real business-video regression completed ({run_id})")
    else:
        print(f"FAIL: real business-video regression exited with code {exit_code} ({run_id})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
