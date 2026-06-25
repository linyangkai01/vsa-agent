# Live API Provider Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenAI-compatible provider overrides for live API acceptance tests without changing the default business configuration path.

**Architecture:** Keep the change narrow. `OpenAIModelAdapter` gains explicit runtime override parameters, and the live acceptance entry reads provider settings from dedicated environment variables before falling back to the current OpenAI-based behavior. Documentation is updated only after the code path and tests are in place.

**Tech Stack:** Python 3.12, pytest, langchain-openai, httpx, PowerShell

## Global Constraints

- Do not add a global provider override system.
- Do not modify `VLLMModelAdapter`.
- Do not change the default mainline behavior that reads `config.model.dev`.
- Keep live provider switching scoped to acceptance validation only.
- Use TDD: write failing tests before implementation changes.

---

## File Structure

**Create**
- `docs/superpowers/plans/2026-06-25-live-api-provider-overrides.md`
  - Execution checklist for provider override support.

**Modify**
- `src/vsa_agent/model_adapter/openai_adapter.py`
  - Accept explicit runtime overrides for `model_name`, `base_url`, and `api_key`.
- `tests/unit/model_adapter/test_model_adapter.py`
  - Lock adapter override precedence and blank-key behavior.
- `tests/acceptance/test_evaluator_live_api.py`
  - Add provider settings helper and wire live tests to it.
- `docs/testing/live-api-validation.md`
  - Document `LIVE_API_*` usage and a DashScope-compatible example.

### Task 1: Add runtime overrides to `OpenAIModelAdapter`

**Files:**
- Modify: `tests/unit/model_adapter/test_model_adapter.py`
- Modify: `src/vsa_agent/model_adapter/openai_adapter.py`

**Interfaces:**
- Consumes: `config.model.dev.base_url`, `config.model.dev.api_key`, `config.model.dev.llm_model`
- Produces: `OpenAIModelAdapter(model_name: str | None = None, base_url: str | None = None, api_key: str | None = None)`

- [ ] **Step 1: Write the failing tests for override precedence**

```python
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
```

- [ ] **Step 2: Run the targeted unit tests to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -q`
Expected: FAIL because `OpenAIModelAdapter` does not yet accept `base_url` or `api_key`

- [ ] **Step 3: Implement the minimal adapter override support**

```python
class OpenAIModelAdapter(BaseModelAdapter):
    """Adapter using OpenAI API (dev mode)."""

    def __init__(
        self,
        model_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        config = get_config()
        dev = config.model.dev
        resolved_model_name = model_name or dev.llm_model
        resolved_base_url = base_url or dev.base_url
        resolved_api_key = api_key if api_key is not None else dev.api_key
        self.llm = ChatOpenAI(
            model=resolved_model_name,
            base_url=resolved_base_url,
            api_key=resolved_api_key if resolved_api_key else None,
            temperature=0,
            max_retries=0,
            http_client=httpx.Client(trust_env=False),
            http_async_client=httpx.AsyncClient(trust_env=False),
        )
```

- [ ] **Step 4: Re-run the targeted unit tests**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/model_adapter/test_model_adapter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/model_adapter/test_model_adapter.py src/vsa_agent/model_adapter/openai_adapter.py
git commit -m "feat: add live provider overrides to openai adapter"
```

### Task 2: Add live API provider-setting resolution in acceptance tests

**Files:**
- Modify: `tests/acceptance/test_evaluator_live_api.py`

**Interfaces:**
- Consumes: environment variables `LIVE_API_MODEL`, `LIVE_API_BASE_URL`, `LIVE_API_KEY`, `OPENAI_API_KEY`
- Produces:
  - `resolve_live_api_settings() -> dict[str, str | None]`
  - `should_run_live_api_validation() -> bool`
  - live tests that instantiate `OpenAIModelAdapter(**resolved_kwargs)`

- [ ] **Step 1: Write the failing tests for environment-variable precedence**

```python
def test_resolve_live_api_settings_prefers_live_overrides(monkeypatch):
    monkeypatch.setenv("LIVE_API_MODEL", "qwen-plus")
    monkeypatch.setenv("LIVE_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("LIVE_API_KEY", "live-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    settings = resolve_live_api_settings()

    assert settings["model_name"] == "qwen-plus"
    assert settings["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings["api_key"] == "live-key"


def test_resolve_live_api_settings_falls_back_to_openai_key(monkeypatch):
    monkeypatch.delenv("LIVE_API_MODEL", raising=False)
    monkeypatch.delenv("LIVE_API_BASE_URL", raising=False)
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    settings = resolve_live_api_settings()

    assert settings["model_name"] is None
    assert settings["base_url"] is None
    assert settings["api_key"] == "openai-key"


def test_live_api_validation_skips_without_required_env(monkeypatch):
    monkeypatch.delenv("LIVE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert should_run_live_api_validation() is False
```

- [ ] **Step 2: Run the targeted acceptance module to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_evaluator_live_api.py -q`
Expected: FAIL because `resolve_live_api_settings()` does not exist yet

- [ ] **Step 3: Implement the minimal settings helper and wire the live tests**

```python
def resolve_live_api_settings() -> dict[str, str | None]:
    live_model = (os.getenv("LIVE_API_MODEL") or "").strip() or None
    live_base_url = (os.getenv("LIVE_API_BASE_URL") or "").strip() or None
    live_api_key = (os.getenv("LIVE_API_KEY") or "").strip() or None
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip() or None
    return {
        "model_name": live_model,
        "base_url": live_base_url,
        "api_key": live_api_key or openai_api_key,
    }


def should_run_live_api_validation() -> bool:
    return bool(resolve_live_api_settings()["api_key"])
```

Use the helper inside both live tests:

```python
    settings = resolve_live_api_settings()
    summary = await summarize_understanding_result(
        actual,
        "what happened",
        model_adapter=OpenAIModelAdapter(**settings),
    )
```

```python
    settings = resolve_live_api_settings()
    result = await execute_search_agent_flow(
        SearchAgentInput(query="find a person walking near a forklift", use_critic=False),
        model_adapter=OpenAIModelAdapter(**settings),
        embed_search=fake_embed_search,
    )
```

- [ ] **Step 4: Re-run the targeted acceptance module**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/acceptance/test_evaluator_live_api.py -q`
Expected: PASS for helper tests, `skip` for live-call tests when no key is configured

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_evaluator_live_api.py
git commit -m "feat: add provider overrides for live api validation"
```

### Task 3: Update documentation and verify the full suite

**Files:**
- Modify: `docs/testing/live-api-validation.md`

**Interfaces:**
- Consumes: implemented `LIVE_API_*` behavior from Task 2
- Produces: user-facing instructions for OpenAI and DashScope-compatible live validation

- [ ] **Step 1: Write the failing doc test expectation**

Add assertions to the existing doc test file:

```python
def test_live_api_validation_doc_mentions_required_env_and_commands():
    doc = Path("docs/testing/live-api-validation.md").read_text(encoding="utf-8")

    assert "LIVE_API_KEY" in doc
    assert "LIVE_API_BASE_URL" in doc
    assert "LIVE_API_MODEL" in doc
    assert "dashscope.aliyuncs.com/compatible-mode/v1" in doc
```

- [ ] **Step 2: Run the doc test to verify failure**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_live_api_docs.py -q`
Expected: FAIL because the current document does not mention `LIVE_API_*`

- [ ] **Step 3: Update the live API validation document**

Include:

```markdown
Live API validation can run in two ways:

- Default OpenAI path: set `OPENAI_API_KEY`
- Provider override path: set `LIVE_API_KEY`, and optionally `LIVE_API_BASE_URL` and `LIVE_API_MODEL`

DashScope-compatible example:

```powershell
$env:CONDA_NO_PLUGINS='true'
$env:PYTHONIOENCODING='utf-8'
$env:LIVE_API_KEY='your-dashscope-key'
$env:LIVE_API_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
$env:LIVE_API_MODEL='qwen-plus'
conda run -n vsa-agent python -m pytest tests/acceptance/test_evaluator_live_api.py -q
```
```

- [ ] **Step 4: Run the doc test and then the full suite**

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests/unit/test_live_api_docs.py -q`
Expected: PASS

Run: `D:\working\anaconda3\envs\vsa-agent\python.exe -m pytest tests -q`
Expected: PASS with the existing live tests skipped unless a key is configured

- [ ] **Step 5: Commit**

```bash
git add docs/testing/live-api-validation.md tests/unit/test_live_api_docs.py
git commit -m "docs: document live api provider overrides"
```

## Self-Review

- Spec coverage: Task 1 covers adapter runtime overrides, Task 2 covers live acceptance env-based provider selection, Task 3 covers docs and verification.
- Placeholder scan: all tasks name exact files, exact tests, and exact commands.
- Type consistency: `OpenAIModelAdapter` override signature is defined once in Task 1 and reused consistently as `OpenAIModelAdapter(**settings)` in Task 2.
