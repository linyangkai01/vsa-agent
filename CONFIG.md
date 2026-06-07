# CONFIG.md

## Project Overview

vsa-agent — Video Safety Analysis Agent for industrial safety inspection.
Built on LangChain/LangGraph, with ModelAdapter for OpenAI-compatible API
(dev) and vLLM (prod) switching.

**Tech stack:** Python 3.13, LangChain, LangGraph, langchain-openai,
FastAPI, fastmcp, Pydantic v2, OpenCV, PyYAML.

## Commands

`ash
# Setup
& C:\working\myproj\vsa-agent\.conda-env\python.exe -m pip install -e .[dev]

# Test (all)
=\"src\"
python -m pytest tests/unit/ -v

# Test (single file)
python -m pytest tests/unit/agents/test_top_agent.py -v

# Lint
ruff check src/

# Run
=\"src\"
python -m vsa_agent.main
`

## Development Conventions

- **Section headers**: # ====={ Name }=====
- **Module constants**: UPPER_SNAKE_CASE
- **Node entry**: logger.debug() at every node start
- **Imports**: stdlib → third-party → first-party, grouped
- **Type annotations**: Required on all public functions
- **Tests**: Mirror src structure under tests/unit/

## Architecture

`
config.yaml → config.py → model_adapter/ → agents/ (LangGraph DAG)
                             ↓                   ↓
                        registry.py          api/routes.py
                             ↓                   ↓
                        tools/              FastAPI server
`

## Module Dependency Rules

- pi/ → gents/ → model_adapter/ + egistry/ → config/
- No reverse imports
- utils/ imported by all, imports from none
- prompt.py is pure constants, no logic
