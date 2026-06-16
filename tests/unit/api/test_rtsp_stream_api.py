"""Tests for api/rtsp_stream_api.py."""

import pytest


@pytest.mark.anyio
async def test_rtsp_stream_api_uses_rtsp_source_type(monkeypatch):
    from vsa_agent.api.rtsp_stream_api import analyze_rtsp_stream

    captured = {}

    async def fake_analyze_video(**kwargs):
        captured.update(kwargs)
        return type("Result", (), {"summary_text": "rtsp summary", "metadata": {}})()

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_video", fake_analyze_video)

    result = await analyze_rtsp_stream(
        sensor_id="camera-1",
        query="describe",
        start_timestamp="",
        end_timestamp="",
    )

    assert result["sensor_id"] == "camera-1"
    assert result["summary_text"] == "rtsp summary"
    assert captured["sensor_id"] == "camera-1"
    assert captured["source_type"] == "rtsp"


@pytest.mark.anyio
async def test_rtsp_stream_api_surfaces_time_window_clip_errors(monkeypatch):
    from vsa_agent.api.rtsp_stream_api import analyze_rtsp_stream
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_analyze_video(**kwargs):
        raise VSTClientError("clip lookup unavailable")

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_video", fake_analyze_video)

    with pytest.raises(VSTClientError, match="clip lookup unavailable"):
        await analyze_rtsp_stream(
            sensor_id="camera-1",
            query="describe",
            start_timestamp="2025-01-01T10:05:00Z",
            end_timestamp="2025-01-01T10:05:30Z",
        )


@pytest.mark.anyio
async def test_rtsp_stream_api_preserves_vst_error_message(monkeypatch):
    from vsa_agent.api.rtsp_stream_api import analyze_rtsp_stream
    from vsa_agent.integrations.vst_client import VSTClientError

    async def fake_analyze_video(**kwargs):
        raise VSTClientError("clip source missing for requested window")

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_video", fake_analyze_video)

    with pytest.raises(VSTClientError, match="clip source missing"):
        await analyze_rtsp_stream(
            sensor_id="camera-1",
            query="describe",
            start_timestamp="2025-01-01T10:05:00Z",
            end_timestamp="2025-01-01T10:05:30Z",
        )
