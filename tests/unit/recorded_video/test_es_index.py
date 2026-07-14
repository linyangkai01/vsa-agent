from __future__ import annotations

from copy import deepcopy

import pytest

from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.es_index import (
    INDEX_SETTINGS,
    RecordedVideoIndex,
    SegmentDocument,
    build_segment_mapping,
)
from vsa_agent.recorded_video.models import segment_id


class FakeApiError(Exception):
    def __init__(self, status_code: int, detail: str = "sensitive backend detail") -> None:
        self.status_code = status_code
        super().__init__(detail)


class FakeIndices:
    def __init__(self) -> None:
        self.indices: dict[str, dict[str, object]] = {}
        self.aliases: dict[str, dict[str, bool | None]] = {}
        self.create_calls: list[dict[str, object]] = []
        self.alias_calls: list[dict[str, object]] = []
        self.failure: Exception | None = None
        self.create_acknowledged = True
        self.alias_acknowledged = True

    def seed(self, *, alias: str, index: str, mappings: dict, settings: dict | None = None) -> None:
        self.indices[index] = {
            "mappings": deepcopy(mappings),
            "settings": deepcopy(settings or INDEX_SETTINGS),
        }
        self.aliases[alias] = {index: True}

    async def exists_alias(self, *, name: str) -> bool:
        self._raise_failure()
        return name in self.aliases

    async def get_alias(self, *, name: str) -> dict[str, object]:
        self._raise_failure()
        return {
            index: {
                "aliases": {
                    name: {} if is_write is None else {"is_write_index": is_write},
                }
            }
            for index, is_write in self.aliases[name].items()
        }

    async def exists(self, *, index: str) -> bool:
        self._raise_failure()
        return index in self.indices

    async def create(self, *, index: str, settings: dict, mappings: dict) -> dict[str, bool]:
        self._raise_failure()
        self.create_calls.append({"index": index, "settings": deepcopy(settings), "mappings": deepcopy(mappings)})
        self.indices[index] = {"settings": deepcopy(settings), "mappings": deepcopy(mappings)}
        return {"acknowledged": self.create_acknowledged}

    async def update_aliases(self, *, actions: list[dict[str, object]]) -> dict[str, bool]:
        self._raise_failure()
        self.alias_calls.append({"actions": deepcopy(actions)})
        add = next(action["add"] for action in actions if "add" in action)
        alias = str(add["alias"])
        self.aliases[alias] = {str(add["index"]): bool(add["is_write_index"])}
        return {"acknowledged": self.alias_acknowledged}

    async def get_mapping(self, *, index: str) -> dict[str, object]:
        self._raise_failure()
        return {index: {"mappings": deepcopy(self.indices[index]["mappings"])}}

    async def get_settings(self, *, index: str, flat_settings: bool = False) -> dict[str, object]:
        self._raise_failure()
        assert flat_settings is True
        settings = self.indices[index]["settings"]
        index_settings = settings["index"]
        return {
            index: {
                "settings": {
                    "index": {
                        "number_of_shards": str(index_settings["number_of_shards"]),
                        "number_of_replicas": str(index_settings["number_of_replicas"]),
                        "mapping": {
                            "total_fields": {"limit": str(index_settings["mapping"]["total_fields"]["limit"])},
                        },
                    }
                }
            }
        }

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure


class FakeElasticsearch:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.option_headers: list[dict[str, str]] = []

    def options(self, *, headers: dict[str, str]):
        self.option_headers.append(dict(headers))
        return self


@pytest.fixture
def fake_es() -> FakeElasticsearch:
    return FakeElasticsearch()


@pytest.fixture
def index(fake_es: FakeElasticsearch) -> RecordedVideoIndex:
    return RecordedVideoIndex(fake_es, alias="vsa-video-segments", index_version="v3")


def _segment_payload() -> dict[str, object]:
    asset_id = "6de491d4-7bf7-4f45-b832-7a9c2f36dd77"
    pipeline_version = "pipeline-v1"
    stable_segment_id = segment_id(asset_id, pipeline_version, 0)
    return {
        "_id": stable_segment_id,
        "asset_id": asset_id,
        "video_id": asset_id,
        "segment_id": stable_segment_id,
        "ordinal": 0,
        "sensor_id": asset_id,
        "source_type": "recorded_video",
        "job_id": "job-1",
        "job_attempt": 1,
        "readiness": {
            "asset_id": asset_id,
            "job_id": "job-1",
            "pipeline_version": pipeline_version,
            "attempt": 1,
        },
        "pipeline_version": pipeline_version,
        "embedding_model": "embed-model",
        "vision_model": "vision-model",
        "prompt_version": "prompt-v1",
        "segmenter_version": "fixed-v1",
        "video_name": "camera.mp4",
        "description": "forklift near worker",
        "start_time": "2026-07-15T08:00:00Z",
        "end_time": "2026-07-15T08:00:30Z",
        "start_offset_ms": 0,
        "end_offset_ms": 30_000,
        "screenshot_url": "derived/thumb.jpg",
        "vector": [0.1, 0.2, 0.3],
    }


@pytest.mark.asyncio
async def test_bootstrap_creates_explicit_versioned_mapping_then_atomically_updates_alias(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    index_name = await index.bootstrap(model="Vendor/Embed Model@2026.07", dims=1024)

    assert index_name.startswith("vsa-video-segments-vendor-embed-model-2026.07-")
    assert index_name.endswith("-v3-d1024")
    assert index_name == await index.bootstrap(model="Vendor/Embed Model@2026.07", dims=1024)
    assert len(fake_es.indices.create_calls) == 1
    created = fake_es.indices.create_calls[0]
    assert created == {
        "index": index_name,
        "settings": INDEX_SETTINGS,
        "mappings": build_segment_mapping(model="Vendor/Embed Model@2026.07", version="v3", dims=1024),
    }
    mapping = created["mappings"]
    assert mapping["dynamic"] == "strict"
    assert mapping["properties"]["description"] == {"type": "text"}
    assert mapping["properties"]["start_time"] == {"type": "date"}
    assert mapping["properties"]["start_offset_ms"] == {"type": "long"}
    assert mapping["properties"]["readiness"] == {
        "type": "object",
        "dynamic": "strict",
        "properties": {
            "asset_id": {"type": "keyword"},
            "job_id": {"type": "keyword"},
            "pipeline_version": {"type": "keyword"},
            "attempt": {"type": "long"},
        },
    }
    assert mapping["properties"]["vector"] == {
        "type": "dense_vector",
        "dims": 1024,
        "similarity": "cosine",
    }
    assert fake_es.indices.alias_calls == [
        {
            "actions": [
                {
                    "add": {
                        "index": index_name,
                        "alias": "vsa-video-segments",
                        "is_write_index": True,
                    }
                },
            ]
        }
    ]
    assert fake_es.option_headers[-1] == {"accept": "application/json", "content-type": "application/json"}


@pytest.mark.asyncio
async def test_existing_compatible_alias_is_validated_without_mutation(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    name = index.index_name(model="embed-model", dims=3)
    fake_es.indices.seed(
        alias="vsa-video-segments",
        index=name,
        mappings=build_segment_mapping(model="embed-model", version="v3", dims=3),
    )

    assert await index.bootstrap(model="embed-model", dims=3) == name
    assert await index.validate_alias(expected_model="embed-model", expected_dims=3) == name
    assert fake_es.indices.create_calls == []
    assert fake_es.indices.alias_calls == []


@pytest.mark.asyncio
async def test_es_814_omitted_object_type_is_semantically_compatible(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    name = index.index_name(model="embed-model", dims=3)
    mapping = build_segment_mapping(model="embed-model", version="v3", dims=3)
    mapping["properties"]["readiness"].pop("type")
    fake_es.indices.seed(alias="vsa-video-segments", index=name, mappings=mapping)

    assert await index.validate_alias(expected_model="embed-model", expected_dims=3) == name


@pytest.mark.asyncio
async def test_existing_alias_with_wrong_vector_dimension_blocks_readiness(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    name = index.index_name(model="embed-model", dims=1536)
    fake_es.indices.seed(
        alias="vsa-video-segments",
        index=name,
        mappings=build_segment_mapping(model="embed-model", version="v3", dims=1536),
    )

    with pytest.raises(RecordedVideoError, match="EMBEDDING_DIMENSION") as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=1024)

    assert caught.value.code is ErrorCode.EMBEDDING_DIMENSION
    assert caught.value.retryable is False
    assert fake_es.indices.create_calls == []
    assert fake_es.indices.alias_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda mapping: mapping["properties"].__setitem__("description", {"type": "keyword"}),
        lambda mapping: mapping["properties"].pop("sensor_id"),
        lambda mapping: mapping["_meta"].__setitem__("embedding_model", "other-model"),
        lambda mapping: mapping["_meta"].__setitem__("index_version", "v2"),
        lambda mapping: mapping["_meta"].__setitem__("unexpected", "value"),
        lambda mapping: mapping["properties"].__setitem__("unexpected", {"type": "keyword"}),
        lambda mapping: mapping["properties"]["vector"].__setitem__("similarity", "dot_product"),
        lambda mapping: mapping.__setitem__("dynamic", True),
    ],
)
async def test_existing_alias_mapping_conflicts_fail_closed(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
    mutate,
) -> None:
    name = index.index_name(model="embed-model", dims=3)
    mapping = build_segment_mapping(model="embed-model", version="v3", dims=3)
    mutate(mapping)
    fake_es.indices.seed(alias="vsa-video-segments", index=name, mappings=mapping)

    with pytest.raises(RecordedVideoError) as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=3)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False
    assert fake_es.indices.create_calls == []
    assert fake_es.indices.alias_calls == []


@pytest.mark.asyncio
async def test_alias_with_wrong_strict_settings_fails_closed(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    name = index.index_name(model="embed-model", dims=3)
    mapping = build_segment_mapping(model="embed-model", version="v3", dims=3)
    fake_es.indices.seed(alias="vsa-video-segments", index=name, mappings=mapping)
    fake_es.indices.indices[name]["settings"]["index"]["mapping"]["total_fields"]["limit"] = 100

    with pytest.raises(RecordedVideoError) as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=3)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert fake_es.indices.alias_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolved_indices",
    [
        {"index-a": True, "index-b": False},
        {"index-a": True, "index-b": True},
    ],
    ids=["multiple-resolved-indices", "multiple-write-indices"],
)
async def test_alias_with_multiple_indices_fails_closed(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
    resolved_indices: dict[str, bool | None],
) -> None:
    fake_es.indices.aliases["vsa-video-segments"] = resolved_indices

    with pytest.raises(RecordedVideoError) as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=3)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_alias_without_explicit_write_index_fails_closed(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
) -> None:
    name = index.index_name(model="embed-model", dims=3)
    fake_es.indices.seed(
        alias="vsa-video-segments",
        index=name,
        mappings=build_segment_mapping(model="embed-model", version="v3", dims=3),
    )
    fake_es.indices.aliases["vsa-video-segments"] = {name: None}

    with pytest.raises(RecordedVideoError) as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=3)

    assert caught.value.code is ErrorCode.CONFIGURATION
    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "alias"])
async def test_unacknowledged_bootstrap_is_retryable_and_retry_reloads_state(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
    operation: str,
) -> None:
    if operation == "create":
        fake_es.indices.create_acknowledged = False
    else:
        fake_es.indices.alias_acknowledged = False

    with pytest.raises(RecordedVideoError) as caught:
        await index.bootstrap(model="embed-model", dims=3)

    assert caught.value.code is ErrorCode.ES_TIMEOUT
    assert caught.value.retryable is True

    fake_es.indices.create_acknowledged = True
    fake_es.indices.alias_acknowledged = True
    name = index.index_name(model="embed-model", dims=3)
    assert await index.bootstrap(model="embed-model", dims=3) == name
    assert len(fake_es.indices.create_calls) == 1
    assert len(fake_es.indices.alias_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (TimeoutError("https://user:secret@es.invalid"), ErrorCode.ES_TIMEOUT, True),
        (FakeApiError(503), ErrorCode.ES_5XX, True),
        (FakeApiError(401), ErrorCode.CONFIGURATION, False),
        (FakeApiError(400), ErrorCode.CONFIGURATION, False),
    ],
)
async def test_elasticsearch_failures_are_classified_without_leaking_credentials(
    index: RecordedVideoIndex,
    fake_es: FakeElasticsearch,
    failure: Exception,
    code: ErrorCode,
    retryable: bool,
) -> None:
    fake_es.indices.failure = failure

    with pytest.raises(RecordedVideoError) as caught:
        await index.validate_alias(expected_model="embed-model", expected_dims=3)

    assert caught.value.code is code
    assert caught.value.retryable is retryable
    assert "secret" not in str(caught.value)
    assert "sensitive backend detail" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_segment_document_accepts_task12_projection_contract_and_rejects_unknown_fields() -> None:
    payload = _segment_payload()
    document = SegmentDocument.model_validate(payload)

    assert document.id == payload["segment_id"]
    assert document.model_dump(by_alias=True)["_id"] == payload["segment_id"]
    assert document.readiness.model_dump() == payload["readiness"]
    aliases = {field.alias or name for name, field in SegmentDocument.model_fields.items()}
    assert aliases - {"_id"} == set(build_segment_mapping(model="embed-model", version="v3", dims=3)["properties"])
    with pytest.raises(ValueError):
        SegmentDocument.model_validate({**document.model_dump(by_alias=True), "unexpected": True})
    with pytest.raises(ValueError, match="finite floats"):
        SegmentDocument.model_validate({**payload, "vector": [1, 2, 3]})
    with pytest.raises(ValueError):
        SegmentDocument.model_validate(
            {
                **payload,
                "readiness": {**payload["readiness"], "authority": "sqlite"},
            }
        )


def test_segment_document_requires_uuid_asset_identity() -> None:
    payload = _segment_payload()
    invalid_asset_id = "asset-1"
    payload.update(
        {
            "asset_id": invalid_asset_id,
            "video_id": invalid_asset_id,
            "sensor_id": invalid_asset_id,
            "readiness": {**payload["readiness"], "asset_id": invalid_asset_id},
        }
    )
    stable_segment_id = segment_id(invalid_asset_id, str(payload["pipeline_version"]), int(payload["ordinal"]))
    payload.update({"_id": stable_segment_id, "segment_id": stable_segment_id})

    with pytest.raises(ValueError, match="UUID"):
        SegmentDocument.model_validate(payload)


def test_segment_document_requires_video_and_sensor_identity() -> None:
    payload = _segment_payload()
    with pytest.raises(ValueError, match="video_id"):
        SegmentDocument.model_validate({**payload, "video_id": "other"})
    with pytest.raises(ValueError, match="sensor_id"):
        SegmentDocument.model_validate({**payload, "sensor_id": "other"})


def test_segment_document_requires_computed_stable_segment_id() -> None:
    payload = _segment_payload()
    wrong_segment_id = "a664668e-32c7-5b6c-9480-4b822c99aa74"

    with pytest.raises(ValueError, match="stable segment_id"):
        SegmentDocument.model_validate({**payload, "_id": wrong_segment_id, "segment_id": wrong_segment_id})
