# vsa-agent Implementation Plan -- Part 1

Goal: Build vsa-agent project skeleton, ModelAdapter, ToolRegistry, and minimal Chat Agent.
Architecture: LangGraph StateGraph for Agent DAG with ModelAdapter for dev/prod switching.
Tech Stack: Python 3.13, LangChain, LangGraph, langchain-openai, Pydantic Settings, FastAPI, fastmcp, pytest.

---

## Task 0: Git Repository Initialization

- [ ] Step 1: git init
- [ ] Step 2: Create .gitignore
- [ ] Step 3: Create directory structure under src/vsa_agent/
- [ ] Step 4: Create all __init__.py files
- [ ] Step 5: Create pyproject.toml with dependencies
- [ ] Step 6: pip install -e ".[dev]"
- [ ] Step 7: git commit -m "init: vsa-agent project skeleton"

---

## Task 1: Configuration System

Files: config.yaml, src/vsa_agent/config.py, tests/unit/test_config.py

- [ ] Step 1: Create config.yaml with model/agent/server sections, dev/prod modes
- [ ] Step 2: Create src/vsa_agent/config.py with Pydantic models (ModelConfig, AgentConfig, ServerConfig, AppConfig)
- [ ] Step 3: Create test_config.py with default value and YAML loading tests
- [ ] Step 4: git commit

---

## Task 2: Model Adapter

Files: src/vsa_agent/model_adapter/base.py, openai_adapter.py, vllm_adapter.py, test_model_adapter.py

- [ ] Step 1: Define BaseModelAdapter abstract class with invoke() and stream() methods
- [ ] Step 2: Implement OpenAIModelAdapter using langchain-openai ChatOpenAI
- [ ] Step 3: Implement VLLMModelAdapter using same ChatOpenAI with custom base_url
- [ ] Step 4: Create ModelAdapterFactory that returns correct adapter based on config mode
- [ ] Step 5: Write tests using mock LLM responses
- [ ] Step 6: git commit

---

## Task 3: Tool Registry

Files: src/vsa_agent/registry.py, tests/unit/test_registry.py

- [ ] Step 1: Create ToolRegistry with decorator-based tool registration
- [ ] Step 2: Create first tool: echo_tool (returns input back)
- [ ] Step 3: Write tests for registration and retrieval
- [ ] Step 4: git commit

---

## Task 4: Minimal Chat Agent (LangGraph DAG)

Files: src/vsa_agent/agents/top_agent.py, data_models.py, test_top_agent.py

- [ ] Step 1: Define AgentDecision enum and AgentState TypedDict
- [ ] Step 2: Build StateGraph with agent_node, tool_node, finalize_node
- [ ] Step 3: Implement conditional routing (CALL_TOOL vs RESPOND)
- [ ] Step 4: Implement streaming via get_stream_writer()
- [ ] Step 5: Write integration test with mock LLM
- [ ] Step 6: git commit

---

## Task 5: FastAPI Server

Files: src/vsa_agent/api/routes.py, health.py, src/vsa_agent/main.py

- [ ] Step 1: Create /health endpoint
- [ ] Step 2: Create /api/chat endpoint that streams agent responses
- [ ] Step 3: Create main.py entry point with uvicorn
- [ ] Step 4: Manual test: curl http://localhost:8000/health
- [ ] Step 5: git commit

---

## Task 6: MCP Server (fastmcp)

Files: src/vsa_agent/mcp/server.py

- [ ] Step 1: Create fastmcp server exposing agent tools as MCP resources
- [ ] Step 2: Register echo_tool and chat function
- [ ] Step 3: Manual test with MCP inspector
- [ ] Step 4: git commit

---

## Task 7: End-to-End Verification

- [ ] Step 1: config.yaml with OPENAI_API_KEY from environment
- [ ] Step 2: Run: python -m vsa_agent.main
- [ ] Step 3: curl POST /api/chat with test message
- [ ] Step 4: Verify streaming response chunks
- [ ] Step 5: git commit -m "feat: end-to-end MVP working"

---

> Next: Part 2 plan covers Search Agent, Summary Agent, Critic Agent, Postprocessing, and Deployment.
