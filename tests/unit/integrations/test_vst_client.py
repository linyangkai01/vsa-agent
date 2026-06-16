"""Tests for VST read-only client integration layer."""

import pytest


@pytest.mark.anyio
async def test_get_stream_info_parses_stream_payload():
    from vsa_agent.integrations.vst_client import VSTClient

    raw_item = {
        "name": "camera-1",
        "url": "rtsp://camera-1/stream",
        "vendor": "acme",
    }

    async def fake_request_json(path: str):
        assert path == "/vst/api/v1/sensor/streams"
        return [
            {
                "stream-123": [
                    raw_item
                ]
            }
        ]

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    result = await client.get_stream_info("camera-1")
    assert result.sensor_id == "camera-1"
    assert result.stream_id == "stream-123"
    assert result.rtsp_url == "rtsp://camera-1/stream"
    assert result.metadata["raw"] == raw_item


@pytest.mark.anyio
async def test_get_timeline_parses_timeline_payload():
    from vsa_agent.integrations.vst_client import VSTClient

    async def fake_request_json(path: str):
        assert path == "/vst/api/v1/storage/timelines"
        return {
            "stream-123": [
                {
                    "startTime": "2025-01-01T10:00:00Z",
                    "endTime": "2025-01-01T10:30:00Z",
                }
            ]
        }

    client = VSTClient(
        external_url="http://localhost:30888",
        request_json=fake_request_json,
        stream_resolver=lambda sensor_id: "stream-123",
    )
    result = await client.get_timeline("camera-1")
    assert result.sensor_id == "camera-1"
    assert result.start_timestamp == "2025-01-01T10:00:00Z"
    assert result.end_timestamp == "2025-01-01T10:30:00Z"


@pytest.mark.anyio
async def test_get_video_clip_returns_clip_result():
    from vsa_agent.integrations.vst_client import VSTClient

    async def fake_request_json(path: str):
        if path == "/vst/api/v1/sensor/streams":
            return [{"stream-123": [{"name": "camera-1", "url": "rtsp://camera-1/stream"}]}]
        raise AssertionError(f"unexpected path {path}")

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    result = await client.get_video_clip(
        "camera-1",
        "2025-01-01T10:05:00Z",
        "2025-01-01T10:05:30Z",
    )
    assert result.sensor_id == "camera-1"
    assert result.start_timestamp == "2025-01-01T10:05:00Z"
    assert result.end_timestamp == "2025-01-01T10:05:30Z"
    assert result.clip_url == "rtsp://camera-1/stream"


@pytest.mark.anyio
async def test_get_video_clip_raises_without_clip_url_or_local_path():
    from vsa_agent.integrations.vst_client import VSTClient
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_request_json(path: str):
        if path == "/vst/api/v1/sensor/streams":
            return [{"stream-123": [{"name": "camera-1"}]}]
        raise AssertionError(f"unexpected path {path}")

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    with pytest.raises(VSTClientError, match="No clip source available"):
        await client.get_video_clip(
            "camera-1",
            "2025-01-01T10:05:00Z",
            "2025-01-01T10:05:30Z",
        )


@pytest.mark.anyio
async def test_get_stream_info_raises_for_missing_sensor():
    from vsa_agent.integrations.vst_client import VSTClient
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_request_json(path: str):
        return [{"stream-123": [{"name": "camera-2", "url": "rtsp://camera-2/stream"}]}]

    client = VSTClient(external_url="http://localhost:30888", request_json=fake_request_json)
    with pytest.raises(VSTClientError, match="camera-1"):
        await client.get_stream_info("camera-1")


@pytest.mark.anyio
async def test_get_timeline_raises_for_missing_bounds():
    from vsa_agent.integrations.vst_client import VSTClient
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_request_json(path: str):
        return {"stream-123": [{}]}

    client = VSTClient(
        external_url="http://localhost:30888",
        request_json=fake_request_json,
        stream_resolver=lambda sensor_id: "stream-123",
    )
    with pytest.raises(VSTClientError, match="camera-1"):
        await client.get_timeline("camera-1")


@pytest.mark.anyio
async def test_request_json_raises_clear_error_without_transport():
    from vsa_agent.integrations.vst_client import VSTClient
    from vsa_agent.integrations.vst_client import VSTClientError

    client = VSTClient(external_url="http://localhost:30888")
    with pytest.raises(VSTClientError, match="inject request_json"):
        await client._request_json("/vst/api/v1/sensor/streams")
