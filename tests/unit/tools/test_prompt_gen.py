"""Tests for tools/prompt_gen.py."""

import pytest

from vsa_agent.tools.prompt_gen import generate_understanding_prompt


@pytest.mark.anyio
async def test_generate_prompt_for_default_intent():
    prompt = await generate_understanding_prompt("person walking near forklift")
    assert "person walking near forklift" in prompt
    assert "Do not hallucinate" in prompt or "DO NOT hallucinate" in prompt


@pytest.mark.anyio
async def test_generate_prompt_for_root_cause_intent():
    query = "why did the incident happen"
    prompt = await generate_understanding_prompt(
        query,
        intent="root_cause",
        context={"source_type": "video_file"},
    )
    lowered = prompt.lower()
    assert query in prompt
    assert "root cause" in lowered or "cause" in lowered
    assert "precursors" in lowered or "contributing conditions" in lowered
