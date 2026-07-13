"""Tests for video_analytics/interface.py."""

import pytest

from vsa_agent.video_analytics.interface import VideoAnalyticsInterface


class TestVideoAnalyticsInterface:
    def test_abstract_class_cannot_instantiate(self):
        with pytest.raises(TypeError):
            VideoAnalyticsInterface()

    def test_concrete_implementation(self):
        class TestImpl(VideoAnalyticsInterface):
            async def search_incidents(self, query, filters=None, time_range=None, top_k=10):
                return []

            async def get_frames(self, sensor_id, time_range, max_frames=50):
                return []

            async def health_check(self):
                return {"status": "ok"}

        impl = TestImpl()
        assert impl is not None
