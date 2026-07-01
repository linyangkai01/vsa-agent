import json
import shutil
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage


TEST_TRACE_DIR = Path("artifacts/test-live-trace")


@pytest.fixture
def trace_dir():
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)
    TEST_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_TRACE_DIR
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)


def test_live_trace_event_writes_jsonl_when_path_is_configured(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_trace_event

    trace_path = trace_dir / "live.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    write_live_trace_event("unit.event", {"api_key": "secret", "value": "ok"})

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "unit.event"
    assert event["payload"] == {"api_key": "<redacted>", "value": "ok"}
    assert event["timestamp"]


def test_live_trace_event_redacts_sensitive_key_variants(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_trace_event

    trace_path = trace_dir / "sensitive.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    write_live_trace_event(
        "unit.sensitive",
        {
            "access_token": "access-secret",
            "refresh-token": "refresh-secret",
            "client_secret": "client-secret",
            "password_hash": "hash-secret",
            "nested": {"serviceAccessToken": "nested-secret"},
            "value": "ok",
        },
    )

    event = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["payload"] == {
        "access_token": "<redacted>",
        "refresh-token": "<redacted>",
        "client_secret": "<redacted>",
        "password_hash": "<redacted>",
        "nested": {"serviceAccessToken": "<redacted>"},
        "value": "ok",
    }


def test_live_trace_event_redacts_compound_api_key_variants(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_trace_event

    trace_path = trace_dir / "compound-api-keys.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    write_live_trace_event(
        "unit.compound-api-keys",
        {
            "openai_api_key": "openai-secret",
            "dashscope_api_key": "dashscope-secret",
            "serviceApiKey": "service-secret",
            "serviceAPIKey": "service-acronym-secret",
            "openaiAPIKey": "openai-acronym-secret",
            "x-api-key": "header-secret",
            "value": "ok",
        },
    )

    event = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["payload"] == {
        "openai_api_key": "<redacted>",
        "dashscope_api_key": "<redacted>",
        "serviceApiKey": "<redacted>",
        "serviceAPIKey": "<redacted>",
        "openaiAPIKey": "<redacted>",
        "x-api-key": "<redacted>",
        "value": "ok",
    }


def test_live_trace_event_is_noop_when_path_is_not_configured(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_trace_event

    monkeypatch.delenv("VSA_LIVE_TRACE_PATH", raising=False)

    write_live_trace_event("unit.event", {"value": "ok"})

    assert list(trace_dir.iterdir()) == []


def test_live_trace_writes_text_and_json_artifacts(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_json_artifact
    from vsa_agent.observability.live_trace import write_live_text_artifact

    artifact_dir = trace_dir / "artifacts"
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(artifact_dir))

    text_path = write_live_text_artifact("tool-results/sample.txt", "hello artifact")
    json_path = write_live_json_artifact("tool-results/sample.json", {"value": "ok"})

    assert text_path == str(artifact_dir / "tool-results" / "sample.txt")
    assert json_path == str(artifact_dir / "tool-results" / "sample.json")
    assert (artifact_dir / "tool-results" / "sample.txt").read_text(encoding="utf-8") == "hello artifact"
    assert json.loads((artifact_dir / "tool-results" / "sample.json").read_text(encoding="utf-8")) == {"value": "ok"}


def test_live_artifact_writers_do_not_overwrite_existing_files(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_json_artifact
    from vsa_agent.observability.live_trace import write_live_text_artifact

    artifact_dir = trace_dir / "artifacts"
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(artifact_dir))

    first_text = write_live_text_artifact("tool-results/repeated.txt", "first")
    second_text = write_live_text_artifact("tool-results/repeated.txt", "second")
    first_json = write_live_json_artifact("tool-results/repeated.json", {"value": "first"})
    second_json = write_live_json_artifact("tool-results/repeated.json", {"value": "second"})

    assert first_text == str(artifact_dir / "tool-results" / "repeated.txt")
    assert second_text == str(artifact_dir / "tool-results" / "repeated-001.txt")
    assert first_json == str(artifact_dir / "tool-results" / "repeated.json")
    assert second_json == str(artifact_dir / "tool-results" / "repeated-001.json")
    assert (artifact_dir / "tool-results" / "repeated.txt").read_text(encoding="utf-8") == "first"
    assert (artifact_dir / "tool-results" / "repeated-001.txt").read_text(encoding="utf-8") == "second"
    assert json.loads((artifact_dir / "tool-results" / "repeated.json").read_text(encoding="utf-8")) == {
        "value": "first"
    }
    assert json.loads((artifact_dir / "tool-results" / "repeated-001.json").read_text(encoding="utf-8")) == {
        "value": "second"
    }


def test_live_json_artifact_redacts_sensitive_key_variants(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_json_artifact

    artifact_dir = trace_dir / "artifacts"
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(artifact_dir))

    json_path = write_live_json_artifact(
        "secrets.json",
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "client_secret": "client-secret",
            "password_hash": "hash-secret",
            "nested": {"serviceAccessToken": "nested-secret"},
            "value": "ok",
        },
    )

    assert json_path == str(artifact_dir / "secrets.json")
    assert json.loads((artifact_dir / "secrets.json").read_text(encoding="utf-8")) == {
        "access_token": "<redacted>",
        "refresh_token": "<redacted>",
        "client_secret": "<redacted>",
        "password_hash": "<redacted>",
        "nested": {"serviceAccessToken": "<redacted>"},
        "value": "ok",
    }


def test_live_json_artifact_redacts_compound_api_key_variants(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_json_artifact

    artifact_dir = trace_dir / "artifacts"
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(artifact_dir))

    json_path = write_live_json_artifact(
        "compound-api-keys.json",
        {
            "openai_api_key": "openai-secret",
            "dashscope_api_key": "dashscope-secret",
            "serviceApiKey": "service-secret",
            "serviceAPIKey": "service-acronym-secret",
            "openaiAPIKey": "openai-acronym-secret",
            "x-api-key": "header-secret",
            "value": "ok",
        },
    )

    assert json_path == str(artifact_dir / "compound-api-keys.json")
    assert json.loads((artifact_dir / "compound-api-keys.json").read_text(encoding="utf-8")) == {
        "openai_api_key": "<redacted>",
        "dashscope_api_key": "<redacted>",
        "serviceApiKey": "<redacted>",
        "serviceAPIKey": "<redacted>",
        "openaiAPIKey": "<redacted>",
        "x-api-key": "<redacted>",
        "value": "ok",
    }


@pytest.mark.parametrize("writer_name", ["write_live_text_artifact", "write_live_json_artifact"])
def test_live_artifact_writers_reject_path_traversal(trace_dir, monkeypatch, writer_name):
    import vsa_agent.observability.live_trace as live_trace

    artifact_dir = trace_dir / "artifacts"
    outside_path = trace_dir / "leak.json"
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(artifact_dir))

    writer = getattr(live_trace, writer_name)
    with pytest.raises(ValueError, match="outside live artifact directory"):
        if writer_name == "write_live_text_artifact":
            writer("../leak.json", "leak")
        else:
            writer("../leak.json", {"value": "leak"})

    assert not outside_path.exists()


def test_live_trace_summarizes_base64_image_payloads(trace_dir, monkeypatch):
    from vsa_agent.observability.live_trace import write_live_trace_event

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    image_url = "data:image/jpeg;base64," + ("a" * 120)

    write_live_trace_event("unit.image", {"image_url": {"url": image_url}})

    event = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    serialized = json.dumps(event)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in serialized
    assert event["payload"]["image_url"]["url"].startswith("data:image/jpeg;base64,<")


@pytest.mark.asyncio
async def test_openai_adapter_logs_model_request_and_response(trace_dir, monkeypatch):
    from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter

    trace_path = trace_dir / "adapter.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    class FakeLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="real model answer")

    adapter = OpenAIModelAdapter.__new__(OpenAIModelAdapter)
    adapter.llm = FakeLLM()
    adapter.model_name = "qwen-plus"
    adapter.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    response = await adapter.invoke([HumanMessage(content="hello model")])

    assert response.content == "real model answer"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == [
        "model.invoke.request",
        "model.invoke.response",
    ]
    assert events[0]["payload"]["messages"][0]["content"] == "hello model"
    assert events[1]["payload"]["response"]["content"] == "real model answer"


@pytest.mark.asyncio
async def test_vllm_adapter_logs_model_request_and_response(trace_dir, monkeypatch):
    from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter

    trace_path = trace_dir / "vllm-adapter.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    class FakeLLM:
        async def ainvoke(self, messages):
            return AIMessage(content="local vllm answer")

    adapter = VLLMModelAdapter.__new__(VLLMModelAdapter)
    adapter.llm = FakeLLM()
    adapter.model_name = "Qwen3-VL-8B-Instruct"
    adapter.base_url = "http://localhost:8000/v1"

    response = await adapter.invoke([HumanMessage(content="hello vllm")])

    assert response.content == "local vllm answer"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == [
        "model.invoke.request",
        "model.invoke.response",
    ]
    assert events[0]["payload"]["adapter"] == "vllm"
    assert events[0]["payload"]["messages"][0]["content"] == "hello vllm"
    assert events[1]["payload"]["response"]["content"] == "local vllm answer"
