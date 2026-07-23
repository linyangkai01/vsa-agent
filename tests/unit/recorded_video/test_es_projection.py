from __future__ import annotations

from copy import deepcopy

import pytest

from vsa_agent.recorded_video import es_index
from vsa_agent.recorded_video.models import segment_id

ASSET_ID = "92db3bce-5caa-4d57-80ba-789851d2345b"
JOB_ID = "job-1"


def _document(*, ordinal: int = 0, attempt: int = 2) -> dict[str, object]:
    stable_id = segment_id(ASSET_ID, "v1", ordinal)
    return {
        "_id": stable_id,
        "asset_id": ASSET_ID,
        "video_id": ASSET_ID,
        "segment_id": stable_id,
        "ordinal": ordinal,
        "sensor_id": ASSET_ID,
        "source_type": "recorded_video",
        "job_id": JOB_ID,
        "job_attempt": attempt,
        "readiness": {
            "asset_id": ASSET_ID,
            "job_id": JOB_ID,
            "pipeline_version": "v1",
            "attempt": attempt,
            "authority": "sqlite",
        },
        "pipeline_version": "v1",
        "embedding_model": "embed-model",
        "vision_model": "vision-model",
        "prompt_version": "prompt-v1",
        "segmenter_version": "segmenter-v1",
        "video_name": "yard.mp4",
        "description": "forklift near worker",
        "start_time": "2026-07-14T08:00:00Z",
        "end_time": "2026-07-14T08:00:05Z",
        "start_offset_ms": ordinal * 5_000,
        "end_offset_ms": (ordinal + 1) * 5_000,
        "screenshot_url": f"/api/v1/videos/{ASSET_ID}/segments/{stable_id}/thumbnail",
        "vector": [0.1, 0.2, 0.3],
    }


class FakeRecordedVideoIndex:
    alias = "vsa-video-segments"

    def __init__(self) -> None:
        self.bootstrap_calls: list[tuple[str, int]] = []

    async def bootstrap(self, model: str, dims: int) -> str:
        self.bootstrap_calls.append((model, dims))
        return "vsa-video-segments-embed-model-v1-d3"


class FakeClient:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def options(self, **kwargs):
        self.options_kwargs = kwargs
        return self

    async def delete_by_query(self, **kwargs):
        self.delete_calls.append(deepcopy(kwargs))
        return {"deleted": 1, "failures": []}


@pytest.mark.asyncio
async def test_projection_bulk_is_attempt_conditional_and_reports_each_failure(monkeypatch) -> None:
    store_type = getattr(es_index, "ElasticsearchProjectionStore", None)
    assert store_type is not None, "Task 16 concrete projection store is missing"

    captured_actions: list[dict[str, object]] = []

    async def fake_streaming_bulk(client, actions, **kwargs):
        del client
        assert kwargs == {
            "raise_on_error": False,
            "raise_on_exception": False,
            "refresh": "wait_for",
        }
        captured_actions.extend(deepcopy(list(actions)))
        first, second = captured_actions
        yield True, {"update": {"_id": first["_id"], "status": 200, "result": "updated"}}
        yield False, {"update": {"_id": second["_id"], "status": 503, "error": {"reason": "secret"}}}

    monkeypatch.setattr(es_index, "async_streaming_bulk", fake_streaming_bulk, raising=False)
    index = FakeRecordedVideoIndex()
    store = store_type(FakeClient(), index=index)
    documents = [_document(ordinal=0), _document(ordinal=1)]

    result = await store.project(documents, job_id=JOB_ID, attempt=2)

    assert result.indexed_ids == [documents[0]["_id"]]
    assert result.failed_ids == [documents[1]["_id"]]
    assert index.bootstrap_calls == [("embed-model", 3)]
    action = captured_actions[0]
    assert action["_op_type"] == "update"
    assert action["_index"] == index.alias
    assert action["_id"] == documents[0]["segment_id"]
    assert action["scripted_upsert"] is True
    assert action["upsert"] == action["script"]["params"]["document"]
    assert action["script"]["params"]["attempt"] == 2
    assert "job_attempt" in action["script"]["source"]
    assert "ctx.op = 'none'" in action["script"]["source"]


@pytest.mark.asyncio
async def test_projection_accepts_pipeline_sqlite_readiness_authority(monkeypatch) -> None:
    captured_actions: list[dict[str, object]] = []

    async def fake_streaming_bulk(_client, actions, **_kwargs):
        captured_actions.extend(deepcopy(list(actions)))
        yield True, {"update": {"_id": captured_actions[0]["_id"], "status": 200}}

    monkeypatch.setattr(es_index, "async_streaming_bulk", fake_streaming_bulk)
    document = _document()
    store = es_index.ElasticsearchProjectionStore(FakeClient(), index=FakeRecordedVideoIndex())

    result = await store.project([document], job_id=JOB_ID, attempt=2)

    assert result.indexed_ids == [document["_id"]]
    assert captured_actions[0]["upsert"]["readiness"]["authority"] == "sqlite"


@pytest.mark.asyncio
async def test_projection_rollback_deletes_only_exact_attempt_and_asset_delete_is_explicit() -> None:
    store_type = getattr(es_index, "ElasticsearchProjectionStore", None)
    assert store_type is not None
    client = FakeClient()
    store = store_type(client, index=FakeRecordedVideoIndex())

    await store.delete_projection(ASSET_ID, JOB_ID, 2)
    await store.delete_asset(ASSET_ID)

    exact, entire_asset = client.delete_calls
    assert exact["index"] == "vsa-video-segments"
    assert exact["conflicts"] == "proceed"
    assert exact["refresh"] is True
    assert exact["query"] == {
        "bool": {
            "filter": [
                {"term": {"asset_id": ASSET_ID}},
                {"term": {"job_id": JOB_ID}},
                {"term": {"job_attempt": 2}},
            ]
        }
    }
    assert entire_asset["query"] == {"term": {"asset_id": ASSET_ID}}
    assert client.options_kwargs == {"headers": {"accept": "application/json", "content-type": "application/json"}}


@pytest.mark.asyncio
async def test_projection_delete_accepts_elasticsearch_8_object_response() -> None:
    class ObjectResponse:
        def __init__(self, body: object) -> None:
            self.body = body

    class WrappedClient(FakeClient):
        async def delete_by_query(self, **kwargs):
            self.delete_calls.append(deepcopy(kwargs))
            return ObjectResponse({"deleted": 1, "failures": [], "timed_out": False})

    store = es_index.ElasticsearchProjectionStore(WrappedClient(), index=FakeRecordedVideoIndex())

    await store.delete_asset(ASSET_ID)


@pytest.mark.asyncio
async def test_projection_rejects_mismatched_call_identity_before_writing(monkeypatch) -> None:
    store_type = getattr(es_index, "ElasticsearchProjectionStore", None)
    assert store_type is not None

    async def forbidden_bulk(*args, **kwargs):
        del args, kwargs
        raise AssertionError("bulk must not run")
        yield

    monkeypatch.setattr(es_index, "async_streaming_bulk", forbidden_bulk, raising=False)
    index = FakeRecordedVideoIndex()
    store = store_type(FakeClient(), index=index)

    with pytest.raises(Exception) as caught:
        await store.project([_document()], job_id=JOB_ID, attempt=3)

    assert type(caught.value).__name__ == "RecordedVideoError"
    assert index.bootstrap_calls == []


@pytest.mark.asyncio
async def test_asset_delete_timeout_is_retryable() -> None:
    class TimedOutClient(FakeClient):
        async def delete_by_query(self, **kwargs):
            self.delete_calls.append(kwargs)
            return {"deleted": 0, "failures": [], "timed_out": True}

    store_type = getattr(es_index, "ElasticsearchProjectionStore", None)
    assert store_type is not None
    store = store_type(TimedOutClient(), index=FakeRecordedVideoIndex())

    with pytest.raises(Exception) as caught:
        await store.delete_asset(ASSET_ID)

    assert type(caught.value).__name__ == "RecordedVideoError"
    assert caught.value.retryable is True
