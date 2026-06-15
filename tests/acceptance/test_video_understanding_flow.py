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
