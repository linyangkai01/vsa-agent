#!/usr/bin/env python3
"""CLI entry point for the recorded-video worker."""

import sys
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from vsa_agent.recorded_video.worker import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
