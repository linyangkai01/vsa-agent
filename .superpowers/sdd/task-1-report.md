# Task 1 Report

## Summary

Added runtime override support to `OpenAIModelAdapter` so callers can supply `model_name`, `base_url`, and `api_key` at construction time. The adapter still defaults to `config.model.dev` when overrides are omitted, and empty API keys are normalized to `None`.

## Files Changed

- `tests/unit/model_adapter/test_model_adapter.py`
- `src/vsa_agent/model_adapter/openai_adapter.py`

## Verification

- `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -q`
- Result: `11 passed`

## Notes

- The change is scoped to `OpenAIModelAdapter` only.
- `VLLMModelAdapter` and the default config-driven mainline behavior were not modified.
