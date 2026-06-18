"""Tests for utils/markdown_parser.py."""

from vsa_agent.utils.markdown_parser import extract_bullet_list
from vsa_agent.utils.markdown_parser import extract_headings
from vsa_agent.utils.markdown_parser import split_sections


def test_extract_headings_filters_by_level():
    markdown = "# Title\n\n## Summary\n\n## Details"
    assert extract_headings(markdown, level=2) == ["Summary", "Details"]


def test_extract_bullet_list_returns_plain_items():
    markdown = "- first\n- second\n\ntext"
    assert extract_bullet_list(markdown) == ["first", "second"]


def test_split_sections_by_h2_returns_section_objects():
    markdown = "# Report\n\n## Summary\nA\n\n## Details\nB"
    sections = split_sections(markdown, heading_level=2)
    assert [section.title for section in sections] == ["Summary", "Details"]
    assert sections[0].content == "A"
    assert sections[1].content == "B"


def test_split_sections_returns_empty_for_no_matching_heading():
    assert split_sections("plain text", heading_level=2) == []
