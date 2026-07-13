import json
import shutil
from pathlib import Path

import pytest

TEST_TRACE_DIR = Path("artifacts/test-video-understanding-live-trace")


@pytest.fixture
def trace_dir():
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)
    TEST_TRACE_DIR.mkdir(parents=True, exist_ok=True)
    yield TEST_TRACE_DIR
    shutil.rmtree(TEST_TRACE_DIR, ignore_errors=True)


def test_extract_frames_logs_metadata_without_base64_payloads(trace_dir, monkeypatch):
    import vsa_agent.tools.video_understanding as module

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))

    class FakeBuffer:
        def tobytes(self):
            return b"fake-jpeg"

    class FakeCapture:
        def __init__(self, path):
            self.path = path
            self.frame_idx = 0

        def isOpened(self):  # noqa: N802 - mirrors the OpenCV protocol
            return True

        def get(self, prop):
            if prop == module.cv2.CAP_PROP_FPS:
                return 10
            if prop == module.cv2.CAP_PROP_FRAME_COUNT:
                return 30
            return 0

        def set(self, prop, value):
            self.frame_idx = value

        def read(self):
            return True, object()

        def release(self):
            pass

    monkeypatch.setattr(module, "_require_cv2", lambda: None)
    monkeypatch.setattr(module.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(module.cv2, "imencode", lambda ext, frame: (True, FakeBuffer()))

    frames, duration, fps, total = module._extract_frames("video.mp4", 3)

    assert len(frames) == 3
    assert duration == 3
    assert fps == 10
    assert total == 30
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "video_understanding.video_metadata" in event_types
    assert "video_understanding.extract_frames" in event_types
    frame_event = events[event_types.index("video_understanding.extract_frames")]
    assert len(frame_event["payload"]["frame_paths"]) == 3
    for frame_path in frame_event["payload"]["frame_paths"]:
        assert Path(frame_path).exists()
    serialized = trace_path.read_text(encoding="utf-8")
    assert "data:image/jpeg;base64" not in serialized


@pytest.mark.asyncio
async def test_analyze_video_segment_logs_vlm_and_normalized_result(trace_dir, monkeypatch):
    from vsa_agent.tools.video_understanding import analyze_video_segment

    trace_path = trace_dir / "trace.jsonl"
    monkeypatch.setenv("VSA_LIVE_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("VSA_LIVE_ARTIFACT_DIR", str(trace_dir))

    async def fake_generate_understanding_prompt(query, context=None):
        return "prompt"

    async def fake_analyze_frames(frames, prompt_text, model_adapter=None, config=None):
        return "person walks through the scene"

    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding.generate_understanding_prompt",
        fake_generate_understanding_prompt,
    )
    monkeypatch.setattr(
        "vsa_agent.tools.video_understanding._analyze_frames",
        fake_analyze_frames,
    )

    result = await analyze_video_segment(frames=["frame-a"], query="what happened")

    assert result.summary_text == "person walks through the scene"
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]
    assert "video_understanding.vlm_result" in event_types
    assert "video_understanding.result" in event_types
    assert (trace_dir / "tool-results" / "video-understanding-raw.txt").exists()
    assert (trace_dir / "tool-results" / "video-understanding-result.json").exists()
