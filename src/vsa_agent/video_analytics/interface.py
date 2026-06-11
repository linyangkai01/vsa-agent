"""VideoAnalyticsInterface abstract base class.

Mirrors NVIDIA interface.py — defines the contract for video analytics backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from vsa_agent.video_analytics.nvschema import Incident


class VideoAnalyticsInterface(ABC):
    """Abstract interface for video analytics operations.

    Provides a unified contract for searching incidents,
    retrieving frames, and analyzing video content.
    """

    @abstractmethod
    async def search_incidents(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        time_range: tuple[float, float] | None = None,
        top_k: int = 10,
    ) -> list[Incident]:
        """Search for incidents matching the query.

        Args:
            query: Natural language query.
            filters: Optional field filters.
            time_range: Optional time range (start_sec, end_sec).
            top_k: Maximum results.

        Returns:
            List of matching incidents.
        """
        ...

    @abstractmethod
    async def get_frames(
        self,
        sensor_id: str,
        time_range: tuple[float, float],
        max_frames: int = 50,
    ) -> list[str]:
        """Retrieve frames from a sensor within a time range.

        Args:
            sensor_id: Camera/sensor identifier.
            time_range: (start_sec, end_sec) time range.
            max_frames: Maximum frames to return.

        Returns:
            List of base64-encoded frame images.
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check the health of the analytics backend.

        Returns:
            Health status dictionary.
        """
        ...
