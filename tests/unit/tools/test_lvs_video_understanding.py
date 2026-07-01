"""Tests for tools/lvs_video_understanding.py."""

import json
from pathlib import Path

import pytest

from vsa_agent.config import AppConfig
from vsa_agent.data_models.understanding import DetectedEvent
from vsa_agent.data_models.understanding import UnderstandingResult


def test_split_video_into_chunks():
    from vsa_agent.tools.lvs_video_understanding import split_video_into_chunks

    chunks = split_video_into_chunks(duration_sec=95, chunk_duration_sec=30)
    assert chunks == [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0), (90.0, 95.0)]


def test_merge_chunk_results_combines_summary_text():
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


def test_merge_chunk_results_merges_adjacent_same_label_events():
    from vsa_agent.tools.lvs_video_understanding import merge_chunk_results

    event_a = DetectedEvent(
        event_id="e1",
        label="walking",
        description="person walking near forklift",
        start_timestamp="00:00:05",
        end_timestamp="00:00:10",
    )
    event_b = DetectedEvent(
        event_id="e2",
        label="walking",
        description="person walking near forklift",
        start_timestamp="00:00:10",
        end_timestamp="00:00:15",
    )

    chunk_a = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk a",
        chunks=[],
        events=[event_a],
    )
    chunk_b = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk b",
        chunks=[],
        events=[event_b],
    )

    merged = merge_chunk_results("what happened", "video_file", [chunk_a, chunk_b])
    assert len(merged.events) == 1
    assert merged.events[0].start_timestamp == "00:00:05"
    assert merged.events[0].end_timestamp == "00:00:15"


def test_merge_chunk_results_keeps_different_label_events_separate():
    from vsa_agent.tools.lvs_video_understanding import merge_chunk_results

    event_a = DetectedEvent(
        event_id="e1",
        label="walking",
        description="person walking near forklift",
        start_timestamp="00:00:05",
        end_timestamp="00:00:10",
    )
    event_b = DetectedEvent(
        event_id="e2",
        label="turning",
        description="forklift turns left",
        start_timestamp="00:00:10",
        end_timestamp="00:00:15",
    )

    chunk_a = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk a",
        chunks=[],
        events=[event_a],
    )
    chunk_b = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk b",
        chunks=[],
        events=[event_b],
    )

    merged = merge_chunk_results("what happened", "video_file", [chunk_a, chunk_b])
    assert len(merged.events) == 2


def test_merge_chunk_results_can_disable_adjacent_event_merge():
    from vsa_agent.tools.lvs_video_understanding import merge_chunk_results

    event_a = DetectedEvent(
        event_id="e1",
        label="walking",
        description="person walking near forklift",
        start_timestamp="00:00:05",
        end_timestamp="00:00:10",
    )
    event_b = DetectedEvent(
        event_id="e2",
        label="walking",
        description="person walking near forklift",
        start_timestamp="00:00:10",
        end_timestamp="00:00:15",
    )

    chunk_a = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk a",
        chunks=[],
        events=[event_a],
    )
    chunk_b = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="chunk b",
        chunks=[],
        events=[event_b],
    )

    merged = merge_chunk_results(
        "what happened",
        "video_file",
        [chunk_a, chunk_b],
        merge_adjacent_events=False,
    )
    assert len(merged.events) == 2


def test_lvs_config_loads_from_app_config():
    cfg = AppConfig.from_yaml("config.yaml")
    assert cfg.lvs_video_understanding.chunk_duration_sec == 30
    assert cfg.lvs_video_understanding.max_frames_per_chunk == 8


@pytest.mark.anyio
async def test_analyze_long_video_calls_segment_analyzer(monkeypatch):
    from vsa_agent.tools.lvs_video_understanding import analyze_long_video

    calls = []

    def fake_probe(video_path):
        assert video_path == "video.mp4"
        return 65.0

    async def fake_analyze_video_segment(**kwargs):
        calls.append((kwargs["start_timestamp"], kwargs["end_timestamp"], kwargs.get("max_frames")))
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text=f"{kwargs['start_timestamp']}-{kwargs['end_timestamp']}",
            chunks=[],
            events=[],
        )

    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding._probe_video_duration", fake_probe)
    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding.analyze_video_segment", fake_analyze_video_segment)

    result = await analyze_long_video(
        video_path="video.mp4",
        query="what happened",
        chunk_duration_sec=30,
        source_type="video_file",
    )

    assert calls == [(0.0, 30.0, 8), (30.0, 60.0, 8), (60.0, 65.0, 8)]
    assert isinstance(result, UnderstandingResult)
    assert "0.0-30.0" in result.summary_text
    assert result.metadata["chunk_count"] == 3
    assert result.metadata["max_frames_per_chunk"] == 8


@pytest.mark.anyio
async def test_analyze_long_video_window_respects_requested_time_range(monkeypatch):
    from vsa_agent.tools.lvs_video_understanding import _analyze_long_video_window

    calls = []

    def fake_probe(video_path):
        assert video_path == "video.mp4"
        return 120.0

    async def fake_analyze_video_segment(**kwargs):
        calls.append((kwargs["start_timestamp"], kwargs["end_timestamp"]))
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text=f"{kwargs['start_timestamp']}-{kwargs['end_timestamp']}",
            chunks=[],
            events=[],
        )

    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding._probe_video_duration", fake_probe)
    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding.analyze_video_segment", fake_analyze_video_segment)

    result = await _analyze_long_video_window(
        video_path="video.mp4",
        query="what happened",
        source_type="video_file",
        chunk_duration_sec=30,
        start_timestamp="PT5S",
        end_timestamp="PT55S",
    )

    assert calls == [(5.0, 35.0), (35.0, 55.0)]
    assert isinstance(result, UnderstandingResult)
    assert "5.0-35.0" in result.summary_text


@pytest.mark.anyio
async def test_analyze_long_video_writes_chunk_trace_events(monkeypatch):
    from vsa_agent.tools.lvs_video_understanding import analyze_long_video

    trace_path = Path("artifacts/test-lvs-video-understanding/trace.jsonl")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.unlink(missing_ok=True)
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))

    def fake_probe(video_path):
        return 65.0

    async def fake_analyze_video_segment(**kwargs):
        return UnderstandingResult(
            query=kwargs["query"],
            source_type=kwargs["source_type"],
            summary_text=f"{kwargs['start_timestamp']}-{kwargs['end_timestamp']}",
            chunks=[],
            events=[],
        )

    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding._probe_video_duration", fake_probe)
    monkeypatch.setattr("vsa_agent.tools.lvs_video_understanding.analyze_video_segment", fake_analyze_video_segment)

    await analyze_long_video(
        video_path="video.mp4",
        query="what happened",
        chunk_duration_sec=30,
        source_type="video_file",
    )

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "lvs_video_understanding.started",
        "lvs_video_understanding.chunk.started",
        "lvs_video_understanding.chunk.completed",
        "lvs_video_understanding.chunk.started",
        "lvs_video_understanding.chunk.completed",
        "lvs_video_understanding.chunk.started",
        "lvs_video_understanding.chunk.completed",
        "lvs_video_understanding.completed",
    ]
    assert events[0]["payload"]["chunk_count"] == 3
    assert events[0]["payload"]["max_frames_per_chunk"] == 8
    assert events[-1]["payload"]["chunk_count"] == 3
    trace_path.unlink(missing_ok=True)
