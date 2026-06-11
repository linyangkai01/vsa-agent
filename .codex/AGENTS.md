# vsa-agent — Video Safety Analysis Agent

## Tech Stack
- Python 3.12, LangChain 1.3, LangGraph 1.2, langchain-openai
- FastAPI 0.136, fastmcp 3.4, Pydantic v2
- OpenCV 4.13 (headless), PyYAML, tenacity
- Hatchling (build)

## Python Environment (conda)
- **Conda env name:** `vsa-agent`
- **Python executable:** `C:\working\orther\anaconda3\envs\vsa-agent\python.exe`
- **Always use this Python** for running scripts, tests, and tools
- Package `vsa_agent` is NOT installed via pip — add `src/` to PYTHONPATH instead

## Commands
- Run: `$env:PYTHONPATH="C:\working\myproj\vsa-agent\src"; & "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m vsa_agent.main`
- Unit tests: `$env:PYTHONPATH="C:\working\myproj\vsa-agent\src"; & "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m pytest tests\unit -v`
- Single test: `$env:PYTHONPATH="C:\working\myproj\vsa-agent\src"; & "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m pytest tests\unit\agents\test_top_agent.py -v`
- Lint: `ruff check src\`
- Install deps: `& "C:\working\orther\anaconda3\envs\vsa-agent\python.exe" -m pip install -r requirements_clean.txt`

## Project Structure
```
src/vsa_agent/
  config.py           — Pydantic config from config.yaml (env var VSA_CONFIG)
  main.py             — uvicorn entrypoint
  registry.py         — Tool/agent module discovery
  prompt.py           — Prompt loading
  agents/             — LangGraph agent DAGs (top_agent, search_agent, critic_agent)
  api/                — FastAPI routes
  data_models/        — Pydantic data models
  embed/              — Embedding
  mcp/                — MCP server
  model_adapter/      — LLM adapter (base, openai_adapter, vllm_adapter)
  tools/              — Tool implementations
  utils/              — Utilities
  video_analytics/    — Video analytics interface
tests/
  unit/               — Unit tests mirroring src structure
  acceptance/         — E2E flow tests
```

## Configuration
- `config.yaml` — main config (model, agent, tools, server, prompts)
- `config_test.yaml` — test config
- Model modes: `dev` (DashScope / OpenAI-compatible) and `prod` (vLLM)
- Dev model: `qwen-plus` (LLM), `qwen3-vl-plus` (VLM) via dashscope.aliyuncs.com
- Prod model: `Qwen3-VL-8B-Instruct` via localhost:8000/v1
- API key env var: `DASHSCOPE_API_KEY` (dev), `OPENAI_API_KEY` (fallback)
- Config path override: `$env:VSA_CONFIG`

## Code Conventions
- Section headers: `# ===== { Name } =====`
- Module constants: `UPPER_SNAKE_CASE`
- Type annotations required on all public functions
- UTF-8 without BOM
- No reverse imports: `utils/` imported by all, imports from none
- Prompts live in `config.yaml` (not `prompt.py`)
- Tool discovery via `config.yaml` `tools.enabled_modules`

## Module Dependency Order
`api/` → `agents/` → `model_adapter/` + `registry/` → `config/`

## Boundaries
- Never commit config.yaml (contains API keys) — already in .gitignore
- Always use the conda `vsa-agent` environment for Python execution
- Always add `src/` to PYTHONPATH before running Python commands
- Always run tests before committing
- Use `pytest-asyncio` for async tests
- Keep test config in `config_test.yaml`