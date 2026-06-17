"""Tests for prompt.py."""
from vsa_agent.prompt import (
    SYSTEM_PROMPT_DEFAULT, SYSTEM_PROMPT_SAFETY_INSPECTION,
    SYSTEM_PROMPT_SAFETY_INCIDENT, SYSTEM_PROMPT_VLM_FORMAT,
    SYSTEM_PROMPT_VIDEO_UNDERSTANDING, VLM_HUMAN_PROMPT_TEMPLATE,
    CRITIC_AGENT_SYSTEM_PROMPT,
)
from vsa_agent import prompt as prompt_module

class TestSystemPrompts:
    def test_default_system_prompt(self):
        assert isinstance(SYSTEM_PROMPT_DEFAULT, str)
        assert len(SYSTEM_PROMPT_DEFAULT) > 50

    def test_default_system_prompt_mentions_report_agent(self):
        assert "report_agent" in SYSTEM_PROMPT_DEFAULT

    def test_default_system_prompt_mentions_multi_report_agent(self):
        assert "multi_report_agent" in SYSTEM_PROMPT_DEFAULT

    def test_default_system_prompt_mentions_chart_tools(self):
        assert "fov_counts_with_chart" in SYSTEM_PROMPT_DEFAULT

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


class TestPromptRegistry:
    def test_exports_prompt_registry_and_all(self):
        assert "default" in prompt_module.PROMPT_REGISTRY
        assert "video_understanding" in prompt_module.PROMPT_REGISTRY
        assert (
            prompt_module.PROMPT_REGISTRY["video_understanding"]
            == prompt_module.SYSTEM_PROMPT_VIDEO_UNDERSTANDING
        )
        assert "SYSTEM_PROMPT_DEFAULT" in prompt_module.__all__
        assert "VLM_HUMAN_PROMPT_TEMPLATE" in prompt_module.__all__
