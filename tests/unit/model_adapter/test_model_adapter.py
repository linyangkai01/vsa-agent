"""Tests for model_adapter/."""

import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage


class TestModelAdapterFactory:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_factory_returns_adapter(self):
        from vsa_agent.model_adapter import BaseModelAdapter
        from vsa_agent.model_adapter import create_model_adapter

        adapter = create_model_adapter()
        assert isinstance(adapter, BaseModelAdapter)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_factory_with_model_name(self):
        from vsa_agent.model_adapter import BaseModelAdapter
        from vsa_agent.model_adapter import create_model_adapter

        adapter = create_model_adapter(model_name="gpt-4o")
        assert isinstance(adapter, BaseModelAdapter)


class TestOpenAIModelAdapter:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_import_and_instantiate(self):
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        adapter = OpenAIModelAdapter(model_name="gpt-4o")
        assert adapter is not None
        assert hasattr(adapter, "llm")

    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    def test_explicit_runtime_overrides_take_precedence(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import ModelConfig
        from vsa_agent.config import ModelDevConfig
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        chat_openai_cls.return_value = MagicMock()
        monkeypatch.setattr(
            "vsa_agent.model_adapter.openai_adapter.get_config",
            lambda: AppConfig(
                model=ModelConfig(
                    mode="dev",
                    dev=ModelDevConfig(
                        provider="openai_compatible",
                        base_url="https://config.example/v1",
                        api_key="config-key",
                        llm_model="config-model",
                        vlm_model="config-vlm",
                    ),
                )
            ),
        )

        OpenAIModelAdapter(
            model_name="override-model",
            base_url="https://override.example/v1",
            api_key="override-key",
        )

        kwargs = chat_openai_cls.call_args.kwargs
        assert kwargs["model"] == "override-model"
        assert kwargs["base_url"] == "https://override.example/v1"
        assert kwargs["api_key"] == "override-key"

    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    def test_blank_api_key_is_treated_as_unset(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import ModelConfig
        from vsa_agent.config import ModelDevConfig
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        chat_openai_cls.return_value = MagicMock()
        monkeypatch.setattr(
            "vsa_agent.model_adapter.openai_adapter.get_config",
            lambda: AppConfig(
                model=ModelConfig(
                    mode="dev",
                    dev=ModelDevConfig(
                        provider="openai_compatible",
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        api_key="",
                        llm_model="qwen-plus",
                        vlm_model="qwen3-vl-plus",
                    ),
                )
            ),
        )

        OpenAIModelAdapter(model_name="qwen-plus")

        kwargs = chat_openai_cls.call_args.kwargs
        assert kwargs["api_key"] is None

    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    def test_runtime_blank_api_key_is_treated_as_unset(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import ModelConfig
        from vsa_agent.config import ModelDevConfig
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        chat_openai_cls.return_value = MagicMock()
        monkeypatch.setattr(
            "vsa_agent.model_adapter.openai_adapter.get_config",
            lambda: AppConfig(
                model=ModelConfig(
                    mode="dev",
                    dev=ModelDevConfig(
                        provider="openai_compatible",
                        base_url="https://config.example/v1",
                        api_key="config-key",
                        llm_model="config-model",
                        vlm_model="config-vlm",
                    ),
                )
            ),
        )

        OpenAIModelAdapter(api_key="")

        kwargs = chat_openai_cls.call_args.kwargs
        assert kwargs["api_key"] is None

    @pytest.mark.asyncio
    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    async def test_invoke_retries_transient_failure(self, chat_openai_cls):
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        llm = MagicMock()
        attempts = {"count": 0}

        async def fake_ainvoke(messages):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("temporary")
            return AIMessage(content="ok")

        llm.ainvoke.side_effect = fake_ainvoke
        chat_openai_cls.return_value = llm

        adapter = OpenAIModelAdapter(model_name="gpt-4o")
        result = await adapter.invoke([HumanMessage(content="hello")])

        assert result.content == "ok"
        assert attempts["count"] == 3
        assert chat_openai_cls.call_args.kwargs["max_retries"] == 0


class TestVLLMModelAdapter:
    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_import_and_instantiate(self):
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

        adapter = VLLMModelAdapter(model_name="Qwen3-VL-8B-Instruct")
        assert adapter is not None
        assert hasattr(adapter, "llm")

    @patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
    def test_bind_tools_delegates_to_underlying_llm(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import ModelConfig
        from vsa_agent.config import ModelProdConfig
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

        llm = MagicMock()
        llm.bind_tools.return_value = llm
        chat_openai_cls.return_value = llm
        monkeypatch.setattr(
            "vsa_agent.model_adapter.vllm_adapter.get_config",
            lambda: AppConfig(
                model=ModelConfig(
                    mode="prod",
                    prod=ModelProdConfig(
                        provider="vllm",
                        base_url="http://localhost:8000/v1",
                        api_key="",
                        llm_model="Qwen3-VL-8B-Instruct",
                        vlm_model="Qwen3-VL-8B-Instruct",
                    ),
                )
            ),
        )

        adapter = VLLMModelAdapter(model_name="Qwen3-VL-8B-Instruct")
        adapter.bind_tools([{"name": "echo"}])

        llm.bind_tools.assert_called_once()
        assert adapter.llm is llm

    @pytest.mark.asyncio
    @patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
    async def test_invoke_retries_transient_failure(self, chat_openai_cls):
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

        llm = MagicMock()
        attempts = {"count": 0}

        async def fake_ainvoke(messages):
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise RuntimeError("temporary")
            return AIMessage(content="ok")

        llm.ainvoke.side_effect = fake_ainvoke
        chat_openai_cls.return_value = llm

        adapter = VLLMModelAdapter(model_name="qwen")
        result = await adapter.invoke([HumanMessage(content="hello")])

        assert result.content == "ok"
        assert attempts["count"] == 2

    @pytest.mark.asyncio
    @patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
    async def test_astream_propagates_error(self, chat_openai_cls):
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

        llm = MagicMock()

        async def fake_astream(messages):
            raise RuntimeError("stream failed")
            yield  # pragma: no cover

        llm.astream.side_effect = fake_astream
        chat_openai_cls.return_value = llm

        adapter = VLLMModelAdapter(model_name="qwen")
        with pytest.raises(RuntimeError):
            async for _ in adapter.astream([HumanMessage(content="hello")]):
                pass
