"""Tests for model_adapter/."""

import os
from unittest.mock import MagicMock
from unittest.mock import patch

from openai import AuthenticationError
from openai import PermissionDeniedError
import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage


class TestModelAdapterFactory:
    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    def test_factory_returns_adapter(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import BackendConfig
        from vsa_agent.config import ProfileConfig
        from vsa_agent.config import RoleBindingConfig
        from vsa_agent.model_adapter import BaseModelAdapter
        from vsa_agent.model_adapter import create_model_adapter

        chat_openai_cls.return_value = MagicMock()
        monkeypatch.setattr(
            "vsa_agent.config.get_config",
            lambda: AppConfig(
                active_profile="test",
                backends={
                    "test_openai": BackendConfig(
                        provider="openai_compatible",
                        base_url="https://api.openai.com/v1",
                        api_key_required=False,
                    )
                },
                profiles={
                    "test": ProfileConfig(
                        llm=RoleBindingConfig(backend="test_openai", model="gpt-4o"),
                        vlm=RoleBindingConfig(backend="test_openai", model="gpt-4o"),
                    )
                },
            ),
        )

        adapter = create_model_adapter()
        assert isinstance(adapter, BaseModelAdapter)
        assert adapter.model_name == "gpt-4o"

    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    def test_factory_with_model_name(self, chat_openai_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import BackendConfig
        from vsa_agent.config import ProfileConfig
        from vsa_agent.config import RoleBindingConfig
        from vsa_agent.model_adapter import BaseModelAdapter
        from vsa_agent.model_adapter import create_model_adapter

        chat_openai_cls.return_value = MagicMock()
        monkeypatch.setattr(
            "vsa_agent.config.get_config",
            lambda: AppConfig(
                active_profile="test",
                backends={
                    "test_openai": BackendConfig(
                        provider="openai_compatible",
                        base_url="https://api.openai.com/v1",
                        api_key_required=False,
                    )
                },
                profiles={
                    "test": ProfileConfig(
                        llm=RoleBindingConfig(backend="test_openai", model="gpt-4o"),
                        vlm=RoleBindingConfig(backend="test_openai", model="gpt-4o"),
                    )
                },
            ),
        )

        adapter = create_model_adapter(model_name="gpt-4o")
        assert isinstance(adapter, BaseModelAdapter)

    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    @patch("vsa_agent.model_adapter.vllm_adapter.ChatOpenAI")
    def test_factory_resolves_role_specific_backends(self, vllm_chat_cls, openai_chat_cls, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import BackendConfig
        from vsa_agent.config import ProfileConfig
        from vsa_agent.config import RoleBindingConfig
        import vsa_agent.model_adapter as model_adapter

        openai_chat_cls.return_value = MagicMock()
        vllm_chat_cls.return_value = MagicMock()
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-secret")
        monkeypatch.delenv("VSA_PROFILE", raising=False)
        monkeypatch.setattr(
            "vsa_agent.config.get_config",
            lambda: AppConfig(
                active_profile="hybrid",
                backends={
                    "dashscope": BackendConfig(
                        provider="openai_compatible",
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        api_key_env="DASHSCOPE_API_KEY",
                    ),
                    "local_vllm": BackendConfig(
                        provider="vllm",
                        base_url="http://localhost:8000/v1",
                        api_key_required=False,
                    ),
                },
                profiles={
                    "hybrid": ProfileConfig(
                        llm=RoleBindingConfig(backend="dashscope", model="qwen3.7-plus"),
                        vlm=RoleBindingConfig(backend="local_vllm", model="Qwen3-VL-8B-Instruct"),
                    )
                },
            ),
        )

        llm_adapter = model_adapter.create_model_adapter(role="llm")
        vlm_adapter = model_adapter.create_model_adapter(role="vlm")

        assert llm_adapter.model_name == "qwen3.7-plus"
        assert llm_adapter.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert openai_chat_cls.call_args.kwargs["api_key"] == "dashscope-secret"
        assert vlm_adapter.model_name == "Qwen3-VL-8B-Instruct"
        assert vlm_adapter.base_url == "http://localhost:8000/v1"


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

    @pytest.mark.asyncio
    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    async def test_invoke_does_not_retry_authentication_error(self, chat_openai_cls):
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        llm = MagicMock()
        response = MagicMock()
        response.request = MagicMock()
        response.status_code = 401
        attempts = {"count": 0}

        async def fake_ainvoke(messages):
            attempts["count"] += 1
            raise AuthenticationError("bad key", response=response, body={"error": {"code": "invalid_api_key"}})

        llm.ainvoke.side_effect = fake_ainvoke
        chat_openai_cls.return_value = llm

        adapter = OpenAIModelAdapter(model_name="gpt-4o")
        with pytest.raises(AuthenticationError):
            await adapter.invoke([HumanMessage(content="hello")])

        assert attempts["count"] == 1

    @pytest.mark.asyncio
    @patch("vsa_agent.model_adapter.openai_adapter.ChatOpenAI")
    async def test_invoke_does_not_retry_permission_or_quota_error(self, chat_openai_cls):
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

        llm = MagicMock()
        response = MagicMock()
        response.request = MagicMock()
        response.status_code = 403
        attempts = {"count": 0}

        async def fake_ainvoke(messages):
            attempts["count"] += 1
            raise PermissionDeniedError(
                "free quota exhausted",
                response=response,
                body={"error": {"code": "AllocationQuota.FreeTierOnly"}},
            )

        llm.ainvoke.side_effect = fake_ainvoke
        chat_openai_cls.return_value = llm

        adapter = OpenAIModelAdapter(model_name="gpt-4o")
        with pytest.raises(PermissionDeniedError):
            await adapter.invoke([HumanMessage(content="hello")])

        assert attempts["count"] == 1


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
