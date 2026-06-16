"""Tests for prompt.py."""
from vsa_agent.prompt import (
    SYSTEM_PROMPT_DEFAULT, SYSTEM_PROMPT_SAFETY_INSPECTION,
    SYSTEM_PROMPT_SAFETY_INCIDENT, SYSTEM_PROMPT_VLM_FORMAT,
    SYSTEM_PROMPT_VIDEO_UNDERSTANDING, VLM_HUMAN_PROMPT_TEMPLATE,
    CRITIC_AGENT_SYSTEM_PROMPT,
)

class TestSystemPrompts:
    def test_default_system_prompt(self):
        assert isinstance(SYSTEM_PROMPT_DEFAULT, str)
        assert len(SYSTEM_PROMPT_DEFAULT) > 50

    def test_default_system_prompt_mentions_report_agent(self):
        assert "report_agent" in SYSTEM_PROMPT_DEFAULT

    def test_vlm_format_prompt(self):
        assert "HALLUCINATE" in SYSTEM_PROMPT_VLM_FORMAT

class TestVLMHumanPrompt:
    def test_contains_placeholder(self):
        assert "{query}" in VLM_HUMAN_PROMPT_TEMPLATE

    def test_formatting(self):
        result = VLM_HUMAN_PROMPT_TEMPLATE.format(query="test query")
        assert "test query" in result

class TestCriticAgentPrompt:
    def test_is_string(self):
        assert isinstance(CRITIC_AGENT_SYSTEM_PROMPT, str)
        assert "critic" in CRITIC_AGENT_SYSTEM_PROMPT.lower()
