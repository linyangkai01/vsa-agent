#!/usr/bin/env python3
"""Create or validate the production recorded-video Elasticsearch alias."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from vsa_agent.config import AppConfig  # noqa: E402
from vsa_agent.recorded_video.bootstrap import bootstrap_recorded_video_index  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = AppConfig.from_yaml(args.config)
        result = asyncio.run(bootstrap_recorded_video_index(config))
    except Exception as error:
        logging.getLogger(__name__).error(
            "recorded_video.index.bootstrap.failed error_type=%s",
            type(error).__name__,
        )
        return 1
    payload = asdict(result)
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True) if args.json_output else payload["index_name"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
