"""Versioned Elasticsearch index contract for recorded-video segments."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.ports import ProjectionReadiness

_CONTRACT_NAME = "vsa-recorded-video-segment"
_CONTRACT_VERSION = 1
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_JSON_HEADERS = {"accept": "application/json", "content-type": "application/json"}

INDEX_SETTINGS: dict[str, Any] = {
    "index": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "mapping": {"total_fields": {"limit": 64}},
    }
}


class SegmentDocument(BaseModel):
    """Validated Task 12 projection document; ``_id`` remains ES metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(alias="_id", serialization_alias="_id")
    asset_id: str
    video_id: str
    segment_id: str
    ordinal: int = Field(ge=0)
    sensor_id: str
    source_type: str
    job_id: str
    job_attempt: int = Field(gt=0)
    readiness: ProjectionReadiness
    pipeline_version: str
    embedding_model: str
    vision_model: str
    prompt_version: str
    segmenter_version: str
    video_name: str
    description: str
    start_time: AwareDatetime
    end_time: AwareDatetime
    start_offset_ms: int = Field(ge=0)
    end_offset_ms: int = Field(ge=0)
    screenshot_url: str | None
    vector: tuple[float, ...]

    @field_validator("vector", mode="before")
    @classmethod
    def validate_vector(cls, vector: Any) -> Any:
        if (
            not isinstance(vector, list | tuple)
            or not vector
            or any(type(value) is not float or not math.isfinite(value) for value in vector)
        ):
            raise ValueError("vector must contain finite floats")
        return vector

    @model_validator(mode="after")
    def validate_identity_and_ranges(self) -> SegmentDocument:
        if self.id != self.segment_id:
            raise ValueError("_id must equal segment_id")
        if self.asset_id != self.video_id:
            raise ValueError("video_id must equal asset_id")
        if self.readiness.asset_id != self.asset_id or self.readiness.job_id != self.job_id:
            raise ValueError("readiness identity does not match the segment document")
        if self.readiness.pipeline_version != self.pipeline_version or self.readiness.attempt != self.job_attempt:
            raise ValueError("readiness version does not match the segment document")
        if self.end_offset_ms <= self.start_offset_ms or self.end_time <= self.start_time:
            raise ValueError("segment end must be after segment start")
        return self


def build_segment_mapping(*, model: str, version: str, dims: int) -> dict[str, Any]:
    """Return the complete immutable mapping for one model/version/dimension tuple."""
    _validate_contract_inputs(model=model, version=version, dims=dims)
    keyword = {"type": "keyword"}
    long = {"type": "long"}
    return {
        "dynamic": "strict",
        "_meta": {
            "contract": _CONTRACT_NAME,
            "contract_version": _CONTRACT_VERSION,
            "embedding_model": model,
            "index_version": version,
            "embedding_dims": dims,
        },
        "properties": {
            "asset_id": dict(keyword),
            "video_id": dict(keyword),
            "segment_id": dict(keyword),
            "ordinal": dict(long),
            "sensor_id": dict(keyword),
            "source_type": dict(keyword),
            "job_id": dict(keyword),
            "job_attempt": dict(long),
            "readiness": {
                "type": "object",
                "dynamic": "strict",
                "properties": {
                    "asset_id": dict(keyword),
                    "job_id": dict(keyword),
                    "pipeline_version": dict(keyword),
                    "attempt": dict(long),
                    "authority": dict(keyword),
                },
            },
            "pipeline_version": dict(keyword),
            "embedding_model": dict(keyword),
            "vision_model": dict(keyword),
            "prompt_version": dict(keyword),
            "segmenter_version": dict(keyword),
            "video_name": dict(keyword),
            "description": {"type": "text"},
            "start_time": {"type": "date"},
            "end_time": {"type": "date"},
            "start_offset_ms": dict(long),
            "end_offset_ms": dict(long),
            "screenshot_url": {"type": "keyword", "index": False},
            "vector": {"type": "dense_vector", "dims": dims, "similarity": "cosine"},
        },
    }


class RecordedVideoIndex:
    """Bootstrap and validate one recorded-video alias without mapping mutation."""

    def __init__(
        self,
        client: Any,
        *,
        alias: str,
        index_version: str = "v1",
        expected_model: str | None = None,
        expected_dims: int | None = None,
    ) -> None:
        _validate_safe_name(alias, label="alias")
        _validate_safe_name(index_version, label="index version")
        if expected_model is not None or expected_dims is not None:
            if expected_model is None or expected_dims is None:
                raise ValueError("expected_model and expected_dims must be configured together")
            _validate_contract_inputs(model=expected_model, version=index_version, dims=expected_dims)
        self._client = client
        self.alias = alias
        self.index_version = index_version
        self.expected_model = expected_model
        self.expected_dims = expected_dims

    def index_name(self, *, model: str, dims: int) -> str:
        _validate_contract_inputs(model=model, version=self.index_version, dims=dims)
        model_slug = _slug(model, max_length=48)
        model_digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:10]
        name = f"{self.alias}-{model_slug}-{model_digest}-{self.index_version}-d{dims}"
        if len(name.encode("utf-8")) > 255:
            raise _configuration_error("INDEX_NAME: versioned index name exceeds the Elasticsearch limit")
        _validate_safe_name(name, label="index name")
        return name

    async def bootstrap(self, model: str, dims: int) -> str:
        """Create a missing exact index and publish its alias in one alias request."""
        _validate_contract_inputs(model=model, version=self.index_version, dims=dims)
        index_name = self.index_name(model=model, dims=dims)
        try:
            client = _json_compatible_client(self._client)
            if await client.indices.exists_alias(name=self.alias):
                return await self._validate_alias(client, expected_model=model, expected_dims=dims)

            if await client.indices.exists(index=index_name):
                await self._validate_index(client, index_name, expected_model=model, expected_dims=dims)
            else:
                response = await client.indices.create(
                    index=index_name,
                    settings=INDEX_SETTINGS,
                    mappings=build_segment_mapping(model=model, version=self.index_version, dims=dims),
                )
                _require_acknowledged(response, operation="create index")

            response = await client.indices.update_aliases(
                actions=[
                    {
                        "add": {
                            "index": index_name,
                            "alias": self.alias,
                            "is_write_index": True,
                        }
                    }
                ]
            )
            _require_acknowledged(response, operation="update alias")
            return index_name
        except RecordedVideoError:
            raise
        except Exception as error:
            raise _classify_es_error(error, operation="bootstrap index") from None

    async def validate_alias(
        self,
        *,
        expected_model: str | None = None,
        expected_dims: int | None = None,
    ) -> str:
        """Perform a non-mutating exact readiness check for the configured alias."""
        model = expected_model or self.expected_model
        dims = expected_dims if expected_dims is not None else self.expected_dims
        if dims is None:
            raise _configuration_error("INDEX_CONFIGURATION: expected embedding dimensions are required")
        if model is not None:
            _validate_contract_inputs(model=model, version=self.index_version, dims=dims)
        elif type(dims) is not int or dims <= 0:
            raise _configuration_error("INDEX_CONFIGURATION: embedding dimensions must be positive")
        try:
            client = _json_compatible_client(self._client)
            return await self._validate_alias(client, expected_model=model, expected_dims=dims)
        except RecordedVideoError:
            raise
        except Exception as error:
            raise _classify_es_error(error, operation="validate alias") from None

    async def _validate_alias(self, client: Any, *, expected_model: str | None, expected_dims: int) -> str:
        if not await client.indices.exists_alias(name=self.alias):
            raise _configuration_error("INDEX_ALIAS_MISSING: recorded-video alias does not exist")
        alias_response = await client.indices.get_alias(name=self.alias)
        if not isinstance(alias_response, Mapping) or len(alias_response) != 1:
            raise _configuration_error("INDEX_ALIAS_CONFLICT: alias must resolve to exactly one index")
        index_name, payload = next(iter(alias_response.items()))
        if not isinstance(index_name, str) or not isinstance(payload, Mapping):
            raise _configuration_error("INDEX_ALIAS_CONFLICT: alias response is invalid")
        aliases = payload.get("aliases")
        alias_config = aliases.get(self.alias) if isinstance(aliases, Mapping) else None
        if not isinstance(alias_config, Mapping) or alias_config.get("is_write_index") is not True:
            raise _configuration_error("INDEX_ALIAS_CONFLICT: alias must identify one explicit write index")
        return await self._validate_index(
            client,
            index_name,
            expected_model=expected_model,
            expected_dims=expected_dims,
        )

    async def _validate_index(
        self,
        client: Any,
        index_name: str,
        *,
        expected_model: str | None,
        expected_dims: int,
    ) -> str:
        mapping_response = await client.indices.get_mapping(index=index_name)
        mapping = _index_payload(mapping_response, index_name, key="mappings")
        properties = mapping.get("properties")
        vector = properties.get("vector") if isinstance(properties, Mapping) else None
        actual_dims = vector.get("dims") if isinstance(vector, Mapping) else None
        if actual_dims != expected_dims:
            raise RecordedVideoError(
                ErrorCode.EMBEDDING_DIMENSION,
                retryable=False,
                message="EMBEDDING_DIMENSION: recorded-video alias uses incompatible vector dimensions",
            )

        meta = mapping.get("_meta")
        actual_model = meta.get("embedding_model") if isinstance(meta, Mapping) else None
        if expected_model is None:
            if not isinstance(actual_model, str) or not actual_model:
                raise _configuration_error("INDEX_MAPPING_CONFLICT: embedding model metadata is missing")
            expected_model = actual_model
        expected_mapping = build_segment_mapping(
            model=expected_model,
            version=self.index_version,
            dims=expected_dims,
        )
        expected_name = self.index_name(model=expected_model, dims=expected_dims)
        if index_name != expected_name or mapping != expected_mapping:
            raise _configuration_error("INDEX_MAPPING_CONFLICT: recorded-video mapping metadata or fields differ")

        settings_response = await client.indices.get_settings(index=index_name, flat_settings=True)
        settings = _index_payload(settings_response, index_name, key="settings")
        if _normalized_contract_settings(settings) != _expected_contract_settings():
            raise _configuration_error("INDEX_SETTINGS_CONFLICT: recorded-video index settings differ")
        return index_name


def _json_compatible_client(client: Any) -> Any:
    """Avoid a v9 vendor media type when the target cluster is Elasticsearch 7/8."""
    options = getattr(client, "options", None)
    if callable(options):
        return options(headers=_JSON_HEADERS)
    return client


def _index_payload(response: Any, index_name: str, *, key: str) -> Mapping[str, Any]:
    if not isinstance(response, Mapping):
        raise _configuration_error(f"INDEX_RESPONSE_INVALID: Elasticsearch {key} response is invalid")
    payload = response.get(index_name)
    value = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(value, Mapping):
        raise _configuration_error(f"INDEX_RESPONSE_INVALID: Elasticsearch {key} response is incomplete")
    return value


def _normalized_contract_settings(settings: Mapping[str, Any]) -> dict[str, str | None]:
    if "index.number_of_shards" in settings:
        return {
            "number_of_shards": _as_setting(settings.get("index.number_of_shards")),
            "number_of_replicas": _as_setting(settings.get("index.number_of_replicas")),
            "total_fields_limit": _as_setting(settings.get("index.mapping.total_fields.limit")),
        }
    index = settings.get("index")
    if not isinstance(index, Mapping):
        return {"number_of_shards": None, "number_of_replicas": None, "total_fields_limit": None}
    mapping = index.get("mapping")
    total_fields = mapping.get("total_fields") if isinstance(mapping, Mapping) else None
    return {
        "number_of_shards": _as_setting(index.get("number_of_shards")),
        "number_of_replicas": _as_setting(index.get("number_of_replicas")),
        "total_fields_limit": _as_setting(total_fields.get("limit") if isinstance(total_fields, Mapping) else None),
    }


def _expected_contract_settings() -> dict[str, str]:
    index = INDEX_SETTINGS["index"]
    return {
        "number_of_shards": str(index["number_of_shards"]),
        "number_of_replicas": str(index["number_of_replicas"]),
        "total_fields_limit": str(index["mapping"]["total_fields"]["limit"]),
    }


def _as_setting(value: Any) -> str | None:
    return str(value).lower() if value is not None else None


def _require_acknowledged(response: Any, *, operation: str) -> None:
    if not isinstance(response, Mapping) or response.get("acknowledged") is not True:
        raise _configuration_error(f"INDEX_NOT_ACKNOWLEDGED: Elasticsearch did not acknowledge {operation}")


def _validate_contract_inputs(*, model: str, version: str, dims: int) -> None:
    if not isinstance(model, str) or not model.strip():
        raise _configuration_error("INDEX_CONFIGURATION: embedding model must not be blank")
    _validate_safe_name(version, label="index version")
    if type(dims) is not int or dims <= 0:
        raise _configuration_error("INDEX_CONFIGURATION: embedding dimensions must be positive")


def _validate_safe_name(value: str, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > 255
        or not _SAFE_NAME.fullmatch(value)
        or value in {".", ".."}
        or ".." in value
    ):
        raise ValueError(f"{label} must be a safe lowercase Elasticsearch name")


def _slug(value: str, *, max_length: int) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-_.")
    slug = re.sub(r"[-_.]{2,}", "-", slug)
    return (slug or "model")[:max_length].rstrip("-_.")


def _configuration_error(message: str) -> RecordedVideoError:
    return RecordedVideoError(ErrorCode.CONFIGURATION, retryable=False, message=f"CONFIGURATION: {message}")


def _classify_es_error(error: Exception, *, operation: str) -> RecordedVideoError:
    status = getattr(error, "status_code", None)
    meta = getattr(error, "meta", None)
    if status is None:
        status = getattr(meta, "status", None)
    class_name = type(error).__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in class_name or status == 408:
        return RecordedVideoError(
            ErrorCode.ES_TIMEOUT,
            retryable=True,
            message=f"ES_TIMEOUT: Elasticsearch {operation} timed out",
        )
    if status == 429 or isinstance(status, int) and 500 <= status <= 599 or "connection" in class_name:
        return RecordedVideoError(
            ErrorCode.ES_5XX,
            retryable=True,
            message=f"ES_5XX: Elasticsearch {operation} failed transiently",
        )
    status_context = f" (status {status})" if isinstance(status, int) else ""
    return _configuration_error(f"ELASTICSEARCH: {operation} failed permanently{status_context}")


__all__ = [
    "INDEX_SETTINGS",
    "RecordedVideoIndex",
    "SegmentDocument",
    "build_segment_mapping",
]
