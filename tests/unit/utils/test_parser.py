"""Tests for utils/parser.py."""

import json

import pytest

from vsa_agent.utils.parser import extract_fenced_block, extract_json_string, parse_json_payload


def test_extract_fenced_block_prefers_matching_language():
    text = 'before```json\n{"ok": true}\n```after'
    assert extract_fenced_block(text, language="json") == '{"ok": true}'


def test_extract_fenced_block_accepts_any_language_when_unspecified():
    text = "```python\nprint('x')\n```"
    assert extract_fenced_block(text) == "print('x')"


def test_extract_json_string_falls_back_to_original_text():
    assert extract_json_string('{"ok": true}') == '{"ok": true}'


def test_parse_json_payload_returns_loaded_object():
    result = parse_json_payload('```json\n{"ok": true}\n```')
    assert result == {"ok": True}


def test_parse_json_payload_raises_on_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        parse_json_payload("```json\nnot-json\n```")
