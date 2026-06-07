import pytest
from unittest.mock import patch, MagicMock
from vsa_agent.model_adapter.base import BaseModelAdapter


class TestBaseModelAdapter:
    def test_base_is_abstract(self):
        with pytest.raises(TypeError):
            BaseModelAdapter()

    def test_factory_dev_mode_returns_adapter(self):
        """create_model_adapter() returns an adapter without crashing."""
        import sys
        mock_langchain = MagicMock()
        mock_langchain.ChatOpenAI = MagicMock(return_value=MagicMock())

        import vsa_agent.config as cfg_mod
        cfg_mod._config = None

        mock_config = MagicMock()
        mock_config.model.mode = 'dev'
        mock_config.model.dev.llm_model = 'gpt-4o'
        mock_config.model.dev.base_url = 'https://api.openai.com/v1'

        try:
            with patch.dict(sys.modules, {'langchain_openai': mock_langchain}):
                with patch('vsa_agent.config.AppConfig.from_yaml', return_value=mock_config):
                    from vsa_agent.model_adapter import create_model_adapter
                    cfg_mod._config = mock_config
                    adapter = create_model_adapter()
                    assert adapter is not None
                    assert type(adapter).__name__ == 'OpenAIModelAdapter'
        finally:
            # Clean up global singleton so other tests get real config
            cfg_mod._config = None