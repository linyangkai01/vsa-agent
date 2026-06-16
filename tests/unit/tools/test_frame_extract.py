"""Tests for tools/frame_extract.py."""
from vsa_agent.tools.frame_extract import has_nvidia_gpu

class TestHasNvidiaGpu:
    def test_returns_bool(self):
        result = has_nvidia_gpu()
        assert isinstance(result, bool)
