"""Tests for tools/frame_extract.py."""

from vsa_agent.tools.frame_extract import _extract_frames, has_nvidia_gpu


class TestHasNvidiaGpu:
    def test_returns_bool(self):
        result = has_nvidia_gpu()
        assert isinstance(result, bool)


class TestExtractFrames:
    def test_uses_shared_frame_selector(self, monkeypatch):
        from vsa_agent.tools import frame_extract

        captured = {}

        class FakeBuffer:
            def tobytes(self):
                return b"abc"

        class FakeCapture:
            def set(self, prop, value):
                captured.setdefault("positions", []).append((prop, value))

            def read(self):
                return True, object()

        def fake_select(total_frames, max_frames, start_frame=0, end_frame=None):
            captured["args"] = (total_frames, max_frames, start_frame, end_frame)
            return [0, 5, 9]

        monkeypatch.setattr(frame_extract, "select_frame_indices", fake_select, raising=False)
        monkeypatch.setattr(frame_extract.cv2, "imencode", lambda ext, frame: (True, FakeBuffer()))

        frames = _extract_frames(
            FakeCapture(),
            fps=10.0,
            total_frames=10,
            start_timestamp=0.0,
            end_timestamp=1.0,
            step_size=0.34,
        )

        assert captured["args"] == (10, 3, 0, 10)
        assert len(frames) == 3
