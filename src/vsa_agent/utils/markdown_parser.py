"""Lightweight markdown parsing helpers for report-style output."""

from __future__ import annotations

from dataclasses import dataclass
import re


HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)
BULLET_RE = re.compile(r"^\s*-\s+(?P<item>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    content: str
    heading_level: int


def extract_headings(markdown: str, level: int | None = None) -> list[str]:
    """Extract markdown heading titles."""
    headings: list[str] = []
    for match in HEADING_RE.finditer(markdown or ""):
        heading_level = len(match.group("hashes"))
        if level is None or heading_level == level:
            headings.append(match.group("title").strip())
    return headings


def extract_bullet_list(markdown: str) -> list[str]:
    """Extract plain text bullet-list items."""
    return [match.group("item").strip() for match in BULLET_RE.finditer(markdown or "")]


def split_sections(markdown: str, heading_level: int = 2) -> list[MarkdownSection]:
    """Split markdown into sections anchored by headings of the target level."""
    if not markdown:
        return []

    matches = [
        match for match in HEADING_RE.finditer(markdown)
        if len(match.group("hashes")) == heading_level
    ]
    if not matches:
        return []

    sections: list[MarkdownSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            MarkdownSection(
                title=match.group("title").strip(),
                content=markdown[start:end].strip(),
                heading_level=heading_level,
            )
        )
    return sections
