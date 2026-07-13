"""Tests for tools/frame_store.py."""

from vsa_agent.tools.frame_store import clear_all, clear_key, get_frames, get_metadata, store_frames


class TestFrameStore:
    def test_store_and_retrieve(self):
        key = store_frames(["frame1", "frame2"], {"source": "test"})
        assert isinstance(key, str)
        assert len(key) > 0
        assert get_frames(key) == ["frame1", "frame2"]

    def test_get_metadata(self):
        key = store_frames(["f1"], {"source": "test", "count": 1})
        meta = get_metadata(key)
        assert meta["source"] == "test"

    def test_get_nonexistent_key(self):
        assert get_frames("nonexistent") is None

    def test_clear_key(self):
        key = store_frames(["f1"], {})
        clear_key(key)
        assert get_frames(key) is None

    def test_clear_all(self):
        store_frames(["f1"], {})
        store_frames(["f2"], {})
        clear_all()
