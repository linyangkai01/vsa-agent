"""Fail-closed OpenAI-compatible providers for recorded-video analysis."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import time
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Segment
from vsa_agent.recorded_video.ports import Embedding, VisionDescription

logger = logging.getLogger(__name__)

_MAX_CONTEXT_ID_LENGTH = 256


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
        timeout_sec = _positive_real(timeout_sec, "timeout_sec")
        concurrency = _positive_int(concurrency, "concurrency")
        self._base_url = _provider_base_url(base_url)
        self._api_key = api_key or None
        self._model = _nonblank_string(model, "model")
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
        asset_id: str,
        job_id: str,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        status: str | int = "network_error"
        started = time.monotonic()
        try:
            async with self._semaphore:
                response = await self._client.post(
                    self._base_url.join(path.lstrip("/")),
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
                "provider.request model=%s status=%s duration_ms=%d stage=%s asset_id=%s job_id=%s",
                self._model,
                status,
                round((time.monotonic() - started) * 1000),
                stage,
                asset_id,
                job_id,
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

    async def describe(
        self,
        frame_keys: Sequence[str | Path],
        segment: Segment,
        *,
        job_id: str,
    ) -> VisionDescription:
        asset_id = _normalize_context_id(segment.asset_id, "asset_id")
        job_id = _normalize_context_id(job_id, "job_id")
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
            asset_id=asset_id,
            job_id=job_id,
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

    async def embed(
        self,
        text: str,
        *,
        expected_dims: int,
        asset_id: str,
        job_id: str,
    ) -> Embedding:
        expected_dims = _positive_int(expected_dims, "expected_dims")
        asset_id = _normalize_context_id(asset_id, "asset_id")
        job_id = _normalize_context_id(job_id, "job_id")
        if not text.strip():
            raise _schema_error("MODEL_INPUT: embedding text must not be blank")

        response = await self._post(
            "embeddings",
            {"model": self._model, "input": text},
            stage="embedding",
            asset_id=asset_id,
            job_id=job_id,
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


def _provider_base_url(value: object) -> httpx.URL:
    try:
        if not isinstance(value, str) or "?" in value or "#" in value:
            raise _configuration_error()
        authority = urlsplit(value).netloc
        endpoint = httpx.URL(value)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.host
            or "@" in authority
            or endpoint.userinfo
            or endpoint.query
            or endpoint.fragment
        ):
            raise _configuration_error()
        return endpoint.copy_with(raw_path=endpoint.raw_path.rstrip(b"/") + b"/")
    except (TypeError, ValueError, httpx.InvalidURL):
        raise _configuration_error() from None


def _positive_real(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _configuration_error(f"CONFIGURATION: {name} must be a finite positive number")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        raise _configuration_error(f"CONFIGURATION: {name} must be a finite positive number") from None
    if not math.isfinite(normalized) or normalized <= 0:
        raise _configuration_error(f"CONFIGURATION: {name} must be a finite positive number")
    return normalized


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise _configuration_error(f"CONFIGURATION: {name} must be a positive integer")
    return value


def _nonblank_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _configuration_error(f"CONFIGURATION: {name} must be a nonblank string")
    return value


def _normalize_context_id(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) > _MAX_CONTEXT_ID_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _configuration_error(f"CONFIGURATION: {name} must be a safe bounded string")
    normalized = value.strip()
    if not normalized:
        raise _configuration_error(f"CONFIGURATION: {name} must not be blank")
    return normalized


def _configuration_error(
    message: str = (
        "CONFIGURATION: provider base_url must be an absolute HTTP(S) URL without userinfo, query, or fragment"
    ),
) -> RecordedVideoError:
    return RecordedVideoError(
        ErrorCode.CONFIGURATION,
        retryable=False,
        message=message,
    )
