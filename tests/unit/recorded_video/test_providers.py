from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Segment
from vsa_agent.recorded_video.providers import OpenAIEmbeddingProvider, OpenAIVisionProvider


def _segment() -> Segment:
    start = datetime(2026, 7, 14, 8, tzinfo=UTC)
    return Segment(
        segment_id="segment-1",
        asset_id="asset-1",
        pipeline_version="v1",
        ordinal=0,
        start_offset_ms=0,
        end_offset_ms=30_000,
        start_time=start,
        end_time=start + timedelta(seconds=30),
    )


def _client(handler: httpx.AsyncBaseTransport | httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://provider.example/v1", transport=handler)


@pytest.mark.asyncio
async def test_vision_sends_openai_compatible_request_and_validates_description(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-frame")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        content = json.dumps({"description": "A forklift passes a worker.", "tags": ["forklift", "worker"]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async with _client(httpx.MockTransport(handler)) as client:
        provider = OpenAIVisionProvider(
            base_url="https://provider.example/v1",
            api_key="top-secret",
            model="vision-model",
            client=client,
        )
        result = await provider.describe(_segment(), [frame])

    body = captured["body"]
    assert isinstance(body, dict)
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer top-secret"
    assert body["model"] == "vision-model"
    assert body["response_format"] == {"type": "json_object"}
    image = body["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,")
    assert result.description == "A forklift passes a worker."
    assert result.tags == ("forklift", "worker")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"description": "valid but tags missing"}),
        json.dumps({"description": "", "tags": []}),
        json.dumps({"description": "valid", "tags": [1]}),
        json.dumps({"description": "valid", "tags": [], "extra": True}),
    ],
)
async def test_vision_rejects_invalid_structured_output(content: str, tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-frame")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )

    async with _client(transport) as client:
        provider = OpenAIVisionProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="vision-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.describe(_segment(), [frame])

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False
    assert "MODEL_RESPONSE_SCHEMA" in str(caught.value)


@pytest.mark.asyncio
async def test_embedding_returns_finite_vector_with_expected_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content) == {"model": "embedding-model", "input": "forklift"}
        return httpx.Response(200, json={"data": [{"embedding": [0.25, -0.5]}]})

    async with _client(httpx.MockTransport(handler)) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key="secret",
            model="embedding-model",
            client=client,
        )
        result = await provider.embed("forklift", expected_dims=2)

    assert result == (0.25, -0.5)


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_permanent() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1]}]}))
    async with _client(transport) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="embedding-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.embed("forklift", expected_dims=4)

    assert caught.value.code is ErrorCode.EMBEDDING_DIMENSION
    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_content",
    [
        b"{}",
        b'{"data":[]}',
        b'{"data":[{"embedding":[]}]}',
        b'{"data":[{"embedding":[true]}]}',
        b'{"data":[{"embedding":["0.1"]}]}',
        b'{"data":[{"embedding":[NaN]}]}',
        b'{"data":[{"embedding":[Infinity]}]}',
    ],
)
async def test_embedding_rejects_invalid_or_non_finite_vectors(response_content: bytes) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=response_content, headers={"content-type": "application/json"})
    )
    async with _client(transport) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="embedding-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.embed("forklift", expected_dims=1)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False
    assert "MODEL_RESPONSE_SCHEMA" in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(429, ErrorCode.MODEL_RATE_LIMIT), (500, ErrorCode.MODEL_5XX), (503, ErrorCode.MODEL_5XX)],
)
async def test_provider_http_transient_failures_are_retryable(status: int, code: ErrorCode) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, text="provider body must not leak"))
    async with _client(transport) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key="secret",
            model="embedding-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.embed("forklift", expected_dims=2)

    assert caught.value.code is code
    assert caught.value.retryable is True
    assert "provider body" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_provider_transport_failures_are_retryable(exception_type: type[httpx.RequestError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("sensitive transport detail", request=request)

    async with _client(httpx.MockTransport(handler)) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key="secret",
            model="embedding-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.embed("forklift", expected_dims=2)

    assert caught.value.code is ErrorCode.MODEL_TIMEOUT
    assert caught.value.retryable is True
    assert "sensitive transport detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_non_rate_limit_4xx_is_permanent_configuration_error() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="secret provider response"))
    async with _client(transport) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key="wrong-secret",
            model="embedding-model",
            client=client,
        )
        with pytest.raises(RecordedVideoError) as caught:
            await provider.embed("forklift", expected_dims=2)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False
    assert "secret provider response" not in str(caught.value)


@pytest.mark.asyncio
async def test_provider_semaphore_bounds_concurrent_requests() -> None:
    active = 0
    maximum = 0
    first_two_started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            first_two_started.set()
        await release.wait()
        active -= 1
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    async with _client(httpx.MockTransport(handler)) as client:
        provider = OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="embedding-model",
            concurrency=2,
            client=client,
        )
        tasks = [asyncio.create_task(provider.embed(str(index), expected_dims=1)) for index in range(4)]
        await asyncio.wait_for(first_two_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert maximum == 2
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_provider_logs_exclude_authorization_frames_and_response_body(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    frame = tmp_path / "secret-frame.jpg"
    frame.write_bytes(b"sensitive-frame-bytes")
    transport = httpx.MockTransport(lambda _: httpx.Response(503, text="sensitive-response-body"))

    async with _client(transport) as client:
        provider = OpenAIVisionProvider(
            base_url="https://provider.example/v1",
            api_key="top-secret-token",
            model="vision-model",
            client=client,
        )
        with caplog.at_level(logging.INFO, logger="vsa_agent.recorded_video.providers"):
            with pytest.raises(RecordedVideoError):
                await provider.describe(_segment(), [frame])

    assert "provider.request" in caplog.text
    assert "vision-model" in caplog.text
    assert "asset-1" in caplog.text
    assert "top-secret-token" not in caplog.text
    assert "Authorization" not in caplog.text
    assert "sensitive-frame-bytes" not in caplog.text
    assert "sensitive-response-body" not in caplog.text
    assert "data:image" not in caplog.text


def test_provider_rejects_invalid_runtime_limits() -> None:
    with pytest.raises(ValueError, match="timeout_sec"):
        OpenAIEmbeddingProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="embedding-model",
            timeout_sec=0,
        )
    with pytest.raises(ValueError, match="concurrency"):
        OpenAIVisionProvider(
            base_url="https://provider.example/v1",
            api_key=None,
            model="vision-model",
            concurrency=0,
        )
