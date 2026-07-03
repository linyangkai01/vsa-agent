# CONFIG.md

## Project Overview

vsa-agent -- a self-owned Video Search and Analysis Agent derived from the
business goals of NVIDIA's `video-search-and-summarization` blueprint, but
without NVIDIA runtime/service lock-in.

The final purpose is to replace NVIDIA-specific dependencies with open,
configurable building blocks while preserving the important business flow:
video search, video understanding, long-video processing, safety QA, report
generation, and replayable observability. The project should run with remote
OpenAI-compatible providers such as Bailian/DashScope during testing and later
support mixed deployments such as remote LLM plus local vLLM/VLM.

Built on LangChain/LangGraph, with ModelAdapter configured by named runtime
profiles for OpenAI-compatible APIs and vLLM endpoints.

**Tech stack:** Python 3.12, LangChain, LangGraph, langchain-openai,
FastAPI, fastmcp, Pydantic v2, OpenCV, PyYAML.

## Commands

```powershell
# Create env
conda create -n vsa-agent python=3.12 pip -y

# Setup (run from repo root; requires network)
conda activate vsa-agent
python -m pip install -e ".[dev]" elasticsearch

# Test (all)
python -m pytest tests\unit -v

# Test (single file)
python -m pytest tests\unit\agents\test_top_agent.py -v

# Lint
python -m ruff check src\

# Run
$env:PYTHONPATH = "src"
python -m vsa_agent.main
```

Live real-video graph validation on Ubuntu:

```bash
cd /data/project/lyk/vsa-agent
export VSA_LIVE_VIDEO_MODE=graph
bash scripts/run_live_top_agent_video_dashscope.sh
LATEST_RUN="$(ls -td artifacts/live-video-runs/* | head -1)"
conda run -n vsa-agent python -m vsa_agent validate-run "$LATEST_RUN"
```

## Architecture

```
config.yaml --> config.py --> model_adapter/ --> agents/ (LangGraph DAG)
                    |                               |
                    |              registry.py  api/routes.py
                    |                   |             |
                    |              tools/        FastAPI server
                    |
              backends/profiles/runtime
              prompts/tools.enabled_modules
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
| active_profile | Default runtime profile name |
| backends | Reusable provider endpoints, API-key env names, and provider type |
| profiles | Role bindings for `llm`, `vlm`, and optional `embedding` |
| runtime | Runner defaults such as conda env, video path, trace dir, QA query |
| agent | max_iterations, planning, postprocessing, log_level, max_history |
| tools | enabled_modules -- Python module paths to import at startup |
| server | host and port for FastAPI |
| prompts | All prompt strings (system, safety, VLM format, etc.) |
| video_understanding | Short-video and source-translation settings |
| lvs_video_understanding | Long-video chunking settings |
| search | Elasticsearch-backed video search settings |

`config.yaml` is the single committed business configuration file. Use `VSA_PROFILE`
to switch between profiles such as `dashscope_remote`, `hybrid_dashscope_llm_local_vlm`,
and `test`.

Sensitive local values live in `config.local.yaml`, which is ignored by git. It is
loaded automatically when present and deep-merged over `config.yaml`. Put keys there
for local experiments, for example:

```yaml
backends:
  dashscope:
    api_key: "your-dashscope-key"
```

Real Elasticsearch video search is disabled by default. Enable it in
`config.local.yaml` and bind an embedding role whose model matches the vectors
stored in the ES index:

```yaml
profiles:
  dashscope_remote:
    embedding:
      backend: dashscope
      model: text-embedding-v4

search:
  enabled: true
  es_endpoint: "http://127.0.0.1:9200"
  embed_index: "your-video-embedding-index"
  behavior_index: "your-object-behavior-index"
  frames_index: "your-frame-index"
  vector_field: "vector"
  embed_confidence_threshold: 0.2
```

Set `VSA_LOCAL_CONFIG` to another file path when a machine needs a different secret
file, or set `VSA_LOCAL_CONFIG=""` to disable local override loading.

## BOM Warning

This project uses UTF-8 without BOM. PowerShell `Set-Content -Encoding utf8`
adds BOM on Windows. Always use the .NET WriteAllText approach:

```powershell
[System.IO.File]::WriteAllText("path/to/file.py",
    $content,
    [System.Text.UTF8Encoding]::new($false))
```
