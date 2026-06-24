"""Acceptance tests for Phase 5 online flow."""

import httpx
import pytest


@pytest.mark.asyncio
async def test_phase5_rtsp_api_flow(monkeypatch):
    from vsa_agent.api.routes import app

    async def fake_analyze_rtsp_stream(**kwargs):
        return {
            "sensor_id": kwargs["sensor_id"],
            "query": kwargs["query"],
            "summary_text": "rtsp summary",
            "metadata": {},
        }

    monkeypatch.setattr("vsa_agent.api.rtsp_stream_api.analyze_rtsp_stream", fake_analyze_rtsp_stream)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/rtsp/analyze",
            json={"sensor_id": "camera-1", "query": "describe"},
        )

    assert response.status_code == 200
    assert response.json()["summary_text"] == "rtsp summary"
