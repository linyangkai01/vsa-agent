# CONFIG.md

## Project Overview

vsa-agent -- Video Safety Analysis Agent for industrial safety inspection.
Built on LangChain/LangGraph, with ModelAdapter for OpenAI-compatible API
(dev) and vLLM (prod) switching.

**Tech stack:** Python 3.12, LangChain, LangGraph, langchain-openai,
FastAPI, fastmcp, Pydantic v2, OpenCV, PyYAML.

## Commands

```powershell
# Setup (requires network in sandbox)
& .conda-env\python.exe -m pip install -e . --no-build-isolation

# Test (all)
& .conda-env\python.exe -m pytest tests\unit -v

# Test (single file)
& .conda-env\python.exe -m pytest tests\unit\agents\test_top_agent.py -v

# Lint
ruff check src\

# Run
$env:PYTHONPATH = "src"
& .conda-env\python.exe -m vsa_agent.main
```

## Architecture

```
config.yaml --> config.py --> model_adapter/ --> agents/ (LangGraph DAG)
                    |                               |
                    |              registry.py  api/routes.py
                    |                   |             |
                    |              tools/        FastAPI server
                    |
              prompts (YAML)
              tools.enabled_modules (YAML)
```

## Development Conventions

- Section headers: `# ===== { Name } =====`
- Module constants: `UPPER_SNAKE_CASE`
- Type annotations: Required on all public functions
- Tests: Mirror src structure under tests/unit/

## Module Dependency Rules

- `api/` --> `agents/` --> `model_adapter/` + `registry/` --> `config/`
- Prompts live in `config.yaml` (no `prompt.py`)
- Tool discovery lives in `config.yaml` (`tools.enabled_modules`)
- No reverse imports. `utils/` imported by all, imports from none.

## config.yaml Structure

| Section | Purpose |
|---|---|
| model | LLM provider, base_url, model names for dev/prod |
| agent | max_iterations, planning, postprocessing, log_level, max_history |
| tools | enabled_modules -- Python module paths to import at startup |
| server | host and port for FastAPI |
| prompts | All prompt strings (system, safety, VLM format, etc.) |

## BOM Warning

This project uses UTF-8 without BOM. PowerShell `Set-Content -Encoding utf8`
adds BOM on Windows. Always use the .NET WriteAllText approach:

```powershell
[System.IO.File]::WriteAllText("path/to/file.py",
    $content,
    [System.Text.UTF8Encoding]::new($false))
```