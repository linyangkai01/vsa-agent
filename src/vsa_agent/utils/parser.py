"""Shared text-output parsing utilities."""

from __future__ import annotations

import json
import re
from typing import Any


FENCED_BLOCK_RE = re.compile(
    r"```(?P<lang>[^\n`]*)\n(?P<body>.*?)```",
    re.DOTALL,
)


def extract_fenced_block(text: str, language: str | None = None) -> str | None:
    """Extract the first fenced block, optionally matching a language."""
    for match in FENCED_BLOCK_RE.finditer(text or ""):
        lang = match.group("lang").strip().lower()
        body = match.group("body").strip()
        if language is None or lang == language.lower():
            return body
    return None


def extract_json_string(text: str) -> str:
    """Extract JSON payload text from fenced code or return the raw text."""
    return (
        extract_fenced_block(text, language="json")
        or extract_fenced_block(text)
        or (text or "")
    ).strip()


def parse_json_payload(text: str) -> Any:
    """Parse a JSON payload from raw/fenced model output."""
    return json.loads(extract_json_string(text))
