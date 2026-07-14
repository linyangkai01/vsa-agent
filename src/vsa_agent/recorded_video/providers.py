"""Fail-closed OpenAI-compatible providers for recorded-video analysis."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Segment

logger = logging.getLogger(__name__)

Embedding = tuple[float, ...]


class VisionDescription(BaseModel):
    """Validated structured output returned by the vision model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    tags: tuple[str, ...]

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("tags must not contain blank values")
            normalized.append(value)
        return tuple(normalized)


class _OpenAIProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_sec: float = 30,
        concurrency: int = 1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("timeout_sec must be positive")
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        if not base_url.strip():
            raise ValueError("base_url must not be blank")
        if not model.strip():
            raise ValueError("model must not be blank")

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or None
        self._model = model
        self._timeout = httpx.Timeout(timeout_sec)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self._timeout, trust_env=False)

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        stage: str,
        asset_id: str | None = None,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        status: str | int = "network_error"
        started = time.monotonic()
        try:
            async with self._semaphore:
                response = await self._client.post(
                    f"{self._base_url}/{path.lstrip('/')}",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            status = response.status_code
        except httpx.TimeoutException:
            status = "timeout"
            raise RecordedVideoError(
                ErrorCode.MODEL_TIMEOUT,
                retryable=True,
                message="MODEL_TIMEOUT: provider request timed out",
            ) from None
        except httpx.RequestError:
            raise RecordedVideoError(
                ErrorCode.MODEL_TIMEOUT,
                retryable=True,
                message="MODEL_TIMEOUT: provider network request failed",
            ) from None
        finally:
            logger.info(
                "provider.request model=%s status=%s duration_ms=%d stage=%s asset_id=%s",
                self._model,
                status,
                round((time.monotonic() - started) * 1000),
                stage,
                asset_id or "-",
            )

        if response.status_code == 429:
            raise RecordedVideoError(
                ErrorCode.MODEL_RATE_LIMIT,
                retryable=True,
                message="MODEL_RATE_LIMIT: provider rate limit exceeded",
            )
        if response.status_code == 408:
            raise RecordedVideoError(
                ErrorCode.MODEL_TIMEOUT,
                retryable=True,
                message="MODEL_TIMEOUT: provider reported request timeout",
            )
        if response.status_code >= 500:
            raise RecordedVideoError(
                ErrorCode.MODEL_5XX,
                retryable=True,
                message=f"MODEL_5XX: provider returned HTTP {response.status_code}",
            )
        if response.status_code >= 400:
            raise RecordedVideoError(
                ErrorCode.CONFIGURATION,
                retryable=False,
                message=f"MODEL_REQUEST: provider returned HTTP {response.status_code}",
            )
        return response

    @staticmethod
    def _response_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _schema_error() from None


class OpenAIVisionProvider(_OpenAIProvider):
    """Describe representative JPEG frames through chat completions."""

    async def describe(self, segment: Segment, frame_keys: Sequence[str | Path]) -> VisionDescription:
        if not frame_keys:
            raise _schema_error("MODEL_INPUT: at least one representative frame is required")

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Describe the visible activity in this video segment. Return only a JSON object "
                    'with exactly two fields: "description" (a non-empty string) and "tags" '
                    "(an array of strings)."
                ),
            }
        ]
        for frame_key in frame_keys:
            try:
                frame = Path(frame_key).read_bytes()
            except OSError:
                raise RecordedVideoError(
                    ErrorCode.CORRUPT_MEDIA,
                    retryable=False,
                    message="CORRUPT_MEDIA: representative frame could not be read",
                ) from None
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(frame).decode('ascii')}"},
                }
            )

        response = await self._post(
            "chat/completions",
            {
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You analyze recorded-video segments and return strict JSON.",
                    },
                    {"role": "user", "content": content},
                ],
                "response_format": {"type": "json_object"},
            },
            stage="analyzing",
            asset_id=segment.asset_id,
        )
        payload = self._response_json(response)
        try:
            raw_content = payload["choices"][0]["message"]["content"]
            if not isinstance(raw_content, str):
                raise TypeError
            result = json.loads(raw_content)
            if not isinstance(result, dict):
                raise TypeError
            return VisionDescription.model_validate(result)
        except (IndexError, KeyError, TypeError, json.JSONDecodeError, ValidationError):
            raise _schema_error() from None


class OpenAIEmbeddingProvider(_OpenAIProvider):
    """Generate one validated vector through the embeddings endpoint."""

    async def embed(self, text: str, *, expected_dims: int) -> Embedding:
        if expected_dims <= 0:
            raise ValueError("expected_dims must be positive")
        if not text.strip():
            raise _schema_error("MODEL_INPUT: embedding text must not be blank")

        response = await self._post(
            "embeddings",
            {"model": self._model, "input": text},
            stage="embedding",
        )
        payload = self._response_json(response)
        try:
            vector = payload["data"][0]["embedding"]
            if not isinstance(vector, list) or not vector:
                raise TypeError
            if any(type(value) is not float or not math.isfinite(value) for value in vector):
                raise TypeError
        except (IndexError, KeyError, TypeError):
            raise _schema_error() from None

        if len(vector) != expected_dims:
            raise RecordedVideoError(
                ErrorCode.EMBEDDING_DIMENSION,
                retryable=False,
                message=f"EMBEDDING_DIMENSION: expected {expected_dims}, received {len(vector)}",
            )
        return tuple(vector)


def _schema_error(message: str = "MODEL_RESPONSE_SCHEMA: provider response failed validation") -> RecordedVideoError:
    return RecordedVideoError(ErrorCode.CONFIGURATION, retryable=False, message=message)
