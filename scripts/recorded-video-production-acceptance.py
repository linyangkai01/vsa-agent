#!/usr/bin/env python3
"""Run the production recorded-video recovery and business-flow acceptance."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from vsa_agent.recorded_video.production_runner import (  # noqa: E402
    ProductionAcceptanceOptions,
    run_production_acceptance,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start the recorded-video stack twice, interrupt the verified Worker, recover three real uploads, "
            "and validate Elasticsearch, original-UI search, media Range, and deletion."
        )
    )
    parser.add_argument(
        "--video",
        action="append",
        required=True,
        type=Path,
        help="Real MP4/MKV; repeat exactly 3 times",
    )
    parser.add_argument("--query", action="append", required=True, help="Repeat once or 3 times")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--index", default="vsa-video-embeddings")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--conda-env", default="vsa-agent")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--es-port", type=int, default=9200)
    parser.add_argument("--ui-port", type=int, default=3000)
    parser.add_argument("--report", type=Path, default=Path("docs/recorded-video-validation.md"))
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--minimum-similarity", type=float, default=0.2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        options = ProductionAcceptanceOptions(
            repo_root=Path.cwd(),
            videos=tuple(args.video),
            queries=tuple(args.query),
            config=args.config,
            index=args.index,
            data_root=args.data_root,
            conda_env=args.conda_env or None,
            api_port=args.api_port,
            es_port=args.es_port,
            ui_port=args.ui_port,
            report=args.report,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            minimum_similarity=args.minimum_similarity,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    try:
        return run_production_acceptance(options)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
