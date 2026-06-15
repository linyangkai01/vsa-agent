"""Acceptance tests for Phase 2 video understanding flow."""

import pytest

from vsa_agent.data_models.understanding import SummaryResult
from vsa_agent.data_models.understanding import UnderstandingResult


class TestVideoUnderstandingFlow:
    @pytest.mark.anyio
    async def test_short_video_returns_dual_track_output(self):
        from vsa_agent.tools.vss_summarize import summarize_understanding_result

        result = UnderstandingResult(
            query="what happened",
            source_type="video_file",
            summary_text="person walking near forklift",
            chunks=[],
            events=[],
        )
        summary = await summarize_understanding_result(result, "what happened")
        assert isinstance(summary, SummaryResult)
        assert summary.text_output
        assert summary.structured_output

    def test_long_video_pipeline_returns_merged_understanding_result(self):
        from vsa_agent.tools.lvs_video_understanding import merge_chunk_results

        chunk_a = UnderstandingResult(
            query="what happened",
            source_type="video_file",
            summary_text="chunk a",
            chunks=[],
            events=[],
        )
        chunk_b = UnderstandingResult(
            query="what happened",
            source_type="video_file",
            summary_text="chunk b",
            chunks=[],
            events=[],
        )
        merged = merge_chunk_results("what happened", "video_file", [chunk_a, chunk_b])
        assert merged.query == "what happened"
        assert merged.source_type == "video_file"
        assert "chunk a" in merged.summary_text
        assert "chunk b" in merged.summary_text

    @pytest.mark.anyio
    async def test_rtsp_sensor_path_uses_vst_clip_resolution(self, monkeypatch):
        from vsa_agent.tools.video_understanding import video_understanding_tool

        class FakeClient:
            async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
                return type("ClipResult", (), {"clip_url": "C:/tmp/clip.mp4", "local_path": None})()

        class FakeCap:
            def isOpened(self):
                return True

            def get(self, prop):
                if prop == 5:
                    return 30.0
                if prop == 7:
                    return 300
                return 0

            def release(self):
                return None

        async def fake_analyze_video_segment(**kwargs):
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="resolved via vst",
                chunks=[],
                events=[],
            )

        monkeypatch.setattr("vsa_agent.tools.video_understanding._get_vst_client", lambda: FakeClient())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_video_segment", fake_analyze_video_segment)

        result = await video_understanding_tool(
            video_path="",
            query="what happened",
            source_type="rtsp",
            sensor_id="camera-1",
            start_timestamp="PT5S",
            end_timestamp="PT10S",
        )
        assert result == "resolved via vst"
