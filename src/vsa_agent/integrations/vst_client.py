"""Read-only VST adapter without NAT dependencies."""

from __future__ import annotations

from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from pydantic import Field


class VSTClientError(RuntimeError):
    """Normalized error raised by the VST read client."""


class VSTStreamInfo(BaseModel):
    sensor_id: str
    stream_id: str
    rtsp_url: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VSTTimeline(BaseModel):
    sensor_id: str
    start_timestamp: str
    end_timestamp: str


class VSTClipResult(BaseModel):
    sensor_id: str
    start_timestamp: str
    end_timestamp: str
    clip_url: str | None = None
    local_path: str | None = None


RequestJson = Callable[[str], Awaitable[Any]]
StreamResolver = Callable[[str], str]


class VSTClient:
    """Read-only VST client with injectable request adapter for testability."""

    def __init__(
        self,
        external_url: str,
        internal_url: str | None = None,
        request_timeout_sec: int = 30,
        request_json: RequestJson | None = None,
        stream_resolver: StreamResolver | None = None,
    ) -> None:
        self.external_url = external_url.rstrip("/")
        self.internal_url = (internal_url or external_url).rstrip("/")
        self.request_timeout_sec = request_timeout_sec
        self._request_json_impl = request_json
        self._stream_resolver = stream_resolver

    async def _request_json(self, path: str) -> Any:
        if self._request_json_impl is None:
            raise VSTClientError(
                "No HTTP adapter configured for VSTClient; inject request_json for non-network use"
            )
        return await self._request_json_impl(path)

    async def get_stream_info(self, sensor_id: str) -> VSTStreamInfo:
        payload = await self._request_json("/vst/api/v1/sensor/streams")
        for entry in payload:
            stream_id = next(iter(entry))
            stream_list = entry[stream_id]
            if not stream_list:
                continue
            item = stream_list[0]
            if item.get("name") == sensor_id:
                return VSTStreamInfo(
                    sensor_id=sensor_id,
                    stream_id=stream_id,
                    rtsp_url=item.get("url"),
                    name=item.get("name"),
                    metadata={"raw": item},
                )
        raise VSTClientError(f"Sensor '{sensor_id}' not found in VST streams response")

    async def get_timeline(self, sensor_id: str) -> VSTTimeline:
        stream_id = self._stream_resolver(sensor_id) if self._stream_resolver is not None else (await self.get_stream_info(sensor_id)).stream_id
        payload = await self._request_json("/vst/api/v1/storage/timelines")
        timeline_list = payload.get(stream_id, [])
        if not timeline_list:
            raise VSTClientError(f"No timeline found for sensor '{sensor_id}'")
        item = timeline_list[0]
        start = item.get("startTime")
        end = item.get("endTime")
        if not start or not end:
            raise VSTClientError(f"Timeline response missing start/end timestamp for sensor '{sensor_id}'")
        return VSTTimeline(
            sensor_id=sensor_id,
            start_timestamp=start,
            end_timestamp=end,
        )

    async def _request_clip_payload(
        self,
        sensor_id: str,
        start_timestamp: str,
        end_timestamp: str,
    ) -> dict[str, Any]:
        path = (
            "/vst/api/v1/storage/clips"
            f"?sensorId={sensor_id}&start={start_timestamp}&end={end_timestamp}"
        )
        payload = await self._request_json(path)
        if not isinstance(payload, dict):
            raise VSTClientError(f"Clip response for sensor '{sensor_id}' is not a JSON object")
        return payload

    async def get_video_clip(
        self,
        sensor_id: str,
        start_timestamp: str,
        end_timestamp: str,
    ) -> VSTClipResult:
        has_time_window = bool(start_timestamp.strip() or end_timestamp.strip())
        if has_time_window:
            try:
                clip_payload = await self._request_clip_payload(
                    sensor_id,
                    start_timestamp,
                    end_timestamp,
                )
            except VSTClientError:
                raise
            except Exception as exc:
                raise VSTClientError(
                    f"Failed to fetch clip for sensor '{sensor_id}' within requested time window"
                ) from exc

            clip_url = clip_payload.get("clip_url") or clip_payload.get("url")
            local_path = clip_payload.get("local_path") or clip_payload.get("localPath")
            if clip_url or local_path:
                return VSTClipResult(
                    sensor_id=sensor_id,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    clip_url=clip_url,
                    local_path=local_path,
                )
            raise VSTClientError(
                f"No clip source available for sensor '{sensor_id}' within requested time window"
            )

        stream = await self.get_stream_info(sensor_id)
        clip_url = stream.rtsp_url
        local_path = stream.metadata.get("raw", {}).get("localPath") or stream.metadata.get(
            "raw", {}
        ).get("local_path")
        if not clip_url and not local_path:
            raise VSTClientError(f"No clip source available for sensor '{sensor_id}'")
        return VSTClipResult(
            sensor_id=sensor_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            clip_url=clip_url,
            local_path=local_path,
        )
