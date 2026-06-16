"""Tests for model_adapter/."""
import os
import pytest
from unittest.mock import patch, MagicMock

class TestModelAdapterFactory:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_factory_returns_adapter(self):
        from vsa_agent.model_adapter import create_model_adapter, BaseModelAdapter
        adapter = create_model_adapter()
        assert isinstance(adapter, BaseModelAdapter)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_factory_with_model_name(self):
        from vsa_agent.model_adapter import create_model_adapter, BaseModelAdapter
        adapter = create_model_adapter(model_name="gpt-4o")
        assert isinstance(adapter, BaseModelAdapter)

class TestOpenAIModelAdapter:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_import_and_instantiate(self):
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter
        adapter = OpenAIModelAdapter(model_name="gpt-4o")
        assert adapter is not None
        assert hasattr(adapter, "llm")

class TestVLLMModelAdapter:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_import_and_instantiate(self):
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter
        adapter = VLLMModelAdapter(model_name="Qwen3-VL-8B-Instruct")
        assert adapter is not None
        assert hasattr(adapter, "llm")
