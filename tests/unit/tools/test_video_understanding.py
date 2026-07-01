"""Tests for tools/video_understanding.py."""
import pytest
from contextlib import asynccontextmanager
from openai import PermissionDeniedError

from vsa_agent.config import AppConfig
from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.prompt import SYSTEM_PROMPT_VIDEO_UNDERSTANDING
from vsa_agent.prompt import VLM_HUMAN_PROMPT_TEMPLATE
from vsa_agent.tools.video_understanding import (
    VideoUnderstandingInput, VideoUnderstandingConfig,
    _extract_frames,
    _analyze_frames, _build_vlm_messages, _normalize_model_response,
    _parse_thinking_from_content, _prepare_video_path, analyze_video,
    analyze_video_segment,
    video_understanding_tool,
)

class TestVideoUnderstandingInput:
    def test_defaults(self):
        inp = VideoUnderstandingInput()
        assert inp.max_frames == 10

class TestVideoUnderstandingConfig:
    def test_defaults(self):
        cfg = VideoUnderstandingConfig()
        assert cfg.max_fps == 2.0
        assert cfg.max_retries == 3
        assert cfg.time_format == "iso"
        assert cfg.source_mode == "local"
        assert cfg.translated_base_dir is None
        assert cfg.vst_sensor_source_map == {}

    def test_loads_from_app_config(self):
        cfg = AppConfig.from_yaml("config.yaml")
        assert cfg.video_understanding.time_format == "iso"
        assert cfg.video_understanding.source_mode == "local"
        assert cfg.video_understanding.translated_base_dir == "C:/mounted-video-store"
        assert cfg.video_understanding.vst_sensor_source_map["camera-1"] == "rtsp://camera-1/stream"

class TestBuildVlmMessages:
    def test_builds_messages(self):
        messages = _build_vlm_messages(["frame1"], "test query")
        assert len(messages) == 2
        assert messages[0].type == "system"
        assert messages[1].type == "human"

    def test_uses_shared_prompt_constants(self):
        messages = _build_vlm_messages(["frame-a"], "what happened")
        assert messages[0].content == SYSTEM_PROMPT_VIDEO_UNDERSTANDING
        text_part = next(
            part["text"]
            for part in messages[1].content
            if part["type"] == "text"
        )
        assert text_part == VLM_HUMAN_PROMPT_TEMPLATE.format(query="what happened")


class TestExtractFrames:
    def test_uses_shared_timestamp_range_selector(self, monkeypatch):
        from vsa_agent.tools import video_understanding

        captured = {}

        class FakeBuffer:
            def tobytes(self):
                return b"abc"

        class FakeCapture:
            def __init__(self, video_path):
                self.video_path = video_path

            def isOpened(self):
                return True

            def get(self, prop):
                if prop == video_understanding.cv2.CAP_PROP_FPS:
                    return 10.0
                if prop == video_understanding.cv2.CAP_PROP_FRAME_COUNT:
                    return 50
                return 0

            def set(self, prop, value):
                captured.setdefault("positions", []).append((prop, value))

            def read(self):
                return True, object()

            def release(self):
                captured["released"] = True

        def fake_select(fps, duration_sec, max_frames, start_ts=0.0, end_ts=None):
            captured["args"] = (fps, duration_sec, max_frames, start_ts, end_ts)
            return [0, 24, 49]

        monkeypatch.setattr(video_understanding, "_require_cv2", lambda: None)
        monkeypatch.setattr(video_understanding.cv2, "VideoCapture", FakeCapture)
        monkeypatch.setattr(video_understanding.cv2, "imencode", lambda ext, frame: (True, FakeBuffer()))
        monkeypatch.setattr(video_understanding, "frames_for_timestamp_range", fake_select, raising=False)

        frames, duration_sec, fps, total_frames = _extract_frames(
            "video.mp4",
            max_frames=3,
            start_timestamp=0.0,
            end_timestamp=5.0,
        )

        assert captured["args"] == (10.0, 5.0, 3, 0.0, 5.0)
        assert len(frames) == 3
        assert duration_sec == 5.0
        assert fps == 10.0
        assert total_frames == 50

class TestNormalizeModelResponse:
    def test_returns_understanding_result(self):
        result = _normalize_model_response(
            query="what happened",
            source_type="video_file",
            raw_output="person walking near forklift",
            prompt_used="watch carefully",
            start_timestamp="2025-01-01T10:00:00Z",
            end_timestamp="2025-01-01T10:00:10Z",
            thinking=None,
        )
        assert isinstance(result, UnderstandingResult)
        assert result.summary_text == "person walking near forklift"
        assert result.chunks[0].normalized_text == "person walking near forklift"

    def test_supports_offset_timestamps(self):
        result = _normalize_model_response(
            query="what happened",
            source_type="video_file",
            raw_output="forklift passes worker",
            prompt_used="watch carefully",
            start_timestamp=5.0,
            end_timestamp="PT10S",
            thinking="chain of thought",
            time_format="offset",
        )
        assert result.chunks[0].start_timestamp == "PT5S"
        assert result.chunks[0].end_timestamp == "PT10S"
        assert result.chunks[0].thinking == "chain of thought"
        assert result.chunks[0].raw_model_output == "forklift passes worker"

    def test_extracts_detected_events_from_timestamp_tags(self):
        result = _normalize_model_response(
            query="what happened",
            source_type="video_file",
            raw_output="<00:00:05> person walks near forklift </timestamp>\n<00:00:09> forklift turns left </timestamp>",
            prompt_used="watch carefully",
            start_timestamp="2025-01-01T10:00:00Z",
            end_timestamp="2025-01-01T10:00:10Z",
            thinking=None,
            video_path="video.mp4",
        )
        assert len(result.events) == 2
        assert result.events[0].description == "person walks near forklift"
        assert result.events[0].start_timestamp == "00:00:05"
        assert result.events[1].description == "forklift turns left"

    def test_creates_fallback_event_when_text_has_no_tags(self):
        result = _normalize_model_response(
            query="what happened",
            source_type="video_file",
            raw_output="worker inspects conveyor belt",
            prompt_used="watch carefully",
            start_timestamp="PT5S",
            end_timestamp="PT10S",
            thinking=None,
            time_format="offset",
            video_path="video.mp4",
        )
        assert len(result.events) == 1
        assert result.events[0].description == "worker inspects conveyor belt"
        assert result.events[0].start_timestamp == "PT5S"
        assert result.events[0].end_timestamp == "PT10S"


class TestPrepareVideoPath:
    def test_normalizes_local_windows_path(self):
        resolved = _prepare_video_path(
            "C:\\videos\\demo.mp4",
            VideoUnderstandingConfig(source_mode="local"),
        )
        assert resolved == "C:/videos/demo.mp4"

    def test_translates_remote_source_when_configured(self, monkeypatch):
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.translate_url",
            lambda url, target_base=None: "C:/tmp/video.mp4",
        )
        resolved = _prepare_video_path(
            "https://example.com/video.mp4",
            VideoUnderstandingConfig(source_mode="translated"),
        )
        assert resolved == "C:/tmp/video.mp4"

    def test_rejects_still_remote_source_after_translation(self, monkeypatch):
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.translate_url",
            lambda url, target_base=None: "https://example.com/video.mp4",
        )
        with pytest.raises(ValueError, match="local video file"):
            _prepare_video_path(
                "https://example.com/video.mp4",
                VideoUnderstandingConfig(source_mode="translated"),
            )

    def test_translates_s3_source_using_configured_base_dir(self):
        resolved = _prepare_video_path(
            "s3://bucket/path/video.mp4",
            VideoUnderstandingConfig(source_mode="translated", translated_base_dir="C:/mounted-video-store"),
        )
        assert resolved == "C:/mounted-video-store/bucket/path/video.mp4"

    def test_allows_http_clip_for_rtsp_source(self, monkeypatch):
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.translate_url",
            lambda url, target_base=None: "http://localhost:30888/vst/api/v1/clip.mp4",
        )
        resolved = _prepare_video_path(
            "http://localhost:30888/vst/api/v1/clip.mp4",
            VideoUnderstandingConfig(source_mode="translated"),
            source_type="rtsp",
        )
        assert resolved == "http://localhost:30888/vst/api/v1/clip.mp4"


class TestResolveVideoSource:
    @pytest.mark.asyncio
    async def test_prefers_explicit_video_path(self):
        from vsa_agent.tools.video_understanding import _resolve_video_source

        config = VideoUnderstandingConfig()
        resolved = await _resolve_video_source(
            video_path="C:/videos/a.mp4",
            sensor_id="camera-1",
            source_type="rtsp",
            config=config,
            start_timestamp="PT5S",
            end_timestamp="PT10S",
        )
        assert resolved == "C:/videos/a.mp4"

    @pytest.mark.asyncio
    async def test_resolves_rtsp_sensor_from_config_map(self):
        from vsa_agent.tools.video_understanding import _resolve_video_source

        config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/stream"})
        resolved = await _resolve_video_source(
            video_path="",
            sensor_id="camera-1",
            source_type="rtsp",
            config=config,
            start_timestamp="",
            end_timestamp="",
        )
        assert resolved == "rtsp://camera-1/stream"

    @pytest.mark.asyncio
    async def test_resolves_rtsp_sensor_via_vst_client_first(self, monkeypatch):
        from vsa_agent.tools.video_understanding import _resolve_video_source

        class FakeClient:
            async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
                return type(
                    "ClipResult",
                    (),
                    {"clip_url": "rtsp://camera-1/from-vst", "local_path": None},
                )()

        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding._get_vst_client",
            lambda: FakeClient(),
        )

        config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/from-map"})
        resolved = await _resolve_video_source(
            video_path="",
            sensor_id="camera-1",
            source_type="rtsp",
            config=config,
            start_timestamp="PT5S",
            end_timestamp="PT10S",
        )
        assert resolved == "rtsp://camera-1/from-vst"

    @pytest.mark.asyncio
    async def test_resolves_rtsp_sensor_without_window_falls_back_to_map_when_vst_fails(self, monkeypatch):
        from vsa_agent.tools.video_understanding import _resolve_video_source
        from vsa_agent.integrations.vst_client import VSTClientError

        class FakeClient:
            async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
                raise VSTClientError("vst unavailable")

        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding._get_vst_client",
            lambda: FakeClient(),
        )

        config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/from-map"})
        resolved = await _resolve_video_source(
            video_path="",
            sensor_id="camera-1",
            source_type="rtsp",
            config=config,
            start_timestamp="",
            end_timestamp="",
        )
        assert resolved == "rtsp://camera-1/from-map"

    @pytest.mark.asyncio
    async def test_resolves_rtsp_sensor_with_window_raises_when_vst_fails(self, monkeypatch):
        from vsa_agent.tools.video_understanding import _resolve_video_source
        from vsa_agent.integrations.vst_client import VSTClientError

        class FakeClient:
            async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
                raise VSTClientError("clip lookup unavailable")

        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding._get_vst_client",
            lambda: FakeClient(),
        )

        config = VideoUnderstandingConfig(vst_sensor_source_map={"camera-1": "rtsp://camera-1/from-map"})
        with pytest.raises(VSTClientError, match="clip lookup unavailable"):
            await _resolve_video_source(
                video_path="",
                sensor_id="camera-1",
                source_type="rtsp",
                config=config,
                start_timestamp="PT5S",
                end_timestamp="PT10S",
            )

    @pytest.mark.asyncio
    async def test_rejects_missing_rtsp_sensor_mapping(self):
        from vsa_agent.tools.video_understanding import _resolve_video_source

        config = VideoUnderstandingConfig(vst_sensor_source_map={})
        with pytest.raises(ValueError, match="No VST source mapping"):
            await _resolve_video_source(
                video_path="",
                sensor_id="camera-unknown",
                source_type="rtsp",
                config=config,
                start_timestamp="",
                end_timestamp="",
            )

class TestParseThinkingFromContent:
    def test_no_thinking(self):
        thinking, answer = _parse_thinking_from_content("Simple answer")
        assert thinking is None
        assert answer == "Simple answer"

    def test_with_thinking_tags(self):
        thinking, answer = _parse_thinking_from_content("Some thinking <answer>Final answer</answer>")
        assert answer == "Final answer"

    def test_empty_string(self):
        thinking, answer = _parse_thinking_from_content("")
        assert thinking is None
        assert answer == ""

    def test_with_explicit_thinking_and_answer_tags(self):
        thinking, answer = _parse_thinking_from_content(
            "<thinking>inspect</thinking><answer>worker falls</answer>"
        )
        assert thinking == "inspect"
        assert answer == "worker falls"


class TestAnalyzeVideoSegment:
    @pytest.mark.asyncio
    async def test_frames_input_skips_rtsp_source_resolution(self, monkeypatch):
        async def fail_if_called(*args, **kwargs):
            raise AssertionError("_resolve_video_source should not run when frames are provided")

        async def fake_prompt(query, intent=None, context=None):
            return "generated prompt"

        async def fake_analyze_frames(frames, query, model_adapter=None, config=None):
            return "plain answer"

        monkeypatch.setattr("vsa_agent.tools.video_understanding._resolve_video_source", fail_if_called)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.generate_understanding_prompt", fake_prompt)
        monkeypatch.setattr("vsa_agent.tools.video_understanding._analyze_frames", fake_analyze_frames)

        result = await analyze_video_segment(
            frames=["frame-a"],
            query="what happened",
            source_type="rtsp",
            sensor_id="camera-unknown",
        )

        assert result.summary_text == "plain answer"

    @pytest.mark.asyncio
    async def test_generates_prompt_when_not_provided(self, monkeypatch):
        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding._extract_frames",
            lambda *args, **kwargs: (["frame-a"], 30.0, 30.0, 900),
        )

        async def fake_prompt(query, intent=None, context=None):
            return "generated prompt"

        async def fake_analyze_frames(frames, query, model_adapter=None, config=None):
            return "plain answer"

        monkeypatch.setattr("vsa_agent.tools.video_understanding.generate_understanding_prompt", fake_prompt)
        monkeypatch.setattr("vsa_agent.tools.video_understanding._analyze_frames", fake_analyze_frames)

        result = await analyze_video_segment(
            video_path="video.mp4",
            query="what happened",
            config=VideoUnderstandingConfig(filter_thinking=True),
        )

        assert result.chunks[0].prompt_used == "generated prompt"

    @pytest.mark.asyncio
    async def test_forwards_segment_bounds_to_extract_frames(self, monkeypatch):
        captured = {}

        def fake_extract_frames(video_path, max_frames, start_timestamp=0.0, end_timestamp=None):
            captured["video_path"] = video_path
            captured["start_timestamp"] = start_timestamp
            captured["end_timestamp"] = end_timestamp
            return ["frame-a"], 30.0, 30.0, 900

        async def fake_analyze_frames(frames, query, model_adapter=None, config=None):
            return "plain answer"

        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding._extract_frames", fake_extract_frames)
        monkeypatch.setattr("vsa_agent.tools.video_understanding._analyze_frames", fake_analyze_frames)

        result = await analyze_video_segment(
            video_path="video.mp4",
            query="what happened",
            start_timestamp="PT5S",
            end_timestamp="12",
            config=VideoUnderstandingConfig(time_format="offset"),
        )

        assert captured["video_path"] == "video.mp4"
        assert captured["start_timestamp"] == 5.0
        assert captured["end_timestamp"] == 12.0
        assert isinstance(result, UnderstandingResult)

    @pytest.mark.asyncio
    async def test_preserves_raw_output_while_filtering_summary(self, monkeypatch):
        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding._extract_frames",
            lambda *args, **kwargs: (["frame-a"], 30.0, 30.0, 900),
        )

        async def fake_analyze_frames(frames, query, model_adapter=None, config=None):
            return "Some thinking <answer>Final answer</answer>"

        monkeypatch.setattr("vsa_agent.tools.video_understanding._analyze_frames", fake_analyze_frames)

        result = await analyze_video_segment(
            video_path="video.mp4",
            query="what happened",
            config=VideoUnderstandingConfig(filter_thinking=True),
        )

        assert result.summary_text == "Final answer"
        assert result.chunks[0].normalized_text == "Final answer"
        assert result.chunks[0].raw_model_output == "Some thinking <answer>Final answer</answer>"
        assert result.chunks[0].thinking == "Some thinking"


class TestAnalyzeFramesRetry:
    @pytest.mark.asyncio
    async def test_prefers_dashscope_vlm_model_env_when_creating_adapter(self, monkeypatch):
        from vsa_agent.config import AppConfig
        from vsa_agent.config import ModelConfig
        from vsa_agent.config import ModelDevConfig
        import vsa_agent.model_adapter as model_adapter

        captured = {}

        class FakeAdapter:
            async def invoke(self, messages):
                return type("Response", (), {"content": "ok"})()

        def fake_create_model_adapter(model_name=None, role=None):
            captured["model_name"] = model_name
            captured["role"] = role
            return FakeAdapter()

        monkeypatch.setenv("DASHSCOPE_VLM_MODEL", "qwen3-vl-flash-2025-10-15")
        monkeypatch.delenv("VSA_VLM_MODEL", raising=False)
        monkeypatch.setattr(model_adapter, "create_model_adapter", fake_create_model_adapter)
        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.get_config",
            lambda: AppConfig(
                model=ModelConfig(
                    mode="dev",
                    dev=ModelDevConfig(
                        provider="openai_compatible",
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                        api_key="",
                        llm_model="qwen-plus",
                        vlm_model="qwen3-vl-plus",
                    ),
                )
            ),
        )

        result = await _analyze_frames(
            ["frame-a"],
            "describe",
            config=VideoUnderstandingConfig(max_retries=1),
        )

        assert result == "ok"
        assert captured["model_name"] == "qwen3-vl-flash-2025-10-15"
        assert captured["role"] == "vlm"

    @pytest.mark.asyncio
    async def test_uses_async_measure_time(self, monkeypatch):
        called = {"value": False}

        @asynccontextmanager
        async def fake_async_measure_time(label, logger=None):
            called["value"] = True
            yield type("Result", (), {"label": label, "elapsed_sec": 0.0})()

        class FakeAdapter:
            async def invoke(self, messages):
                return type("Response", (), {"content": "ok"})()

        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.async_measure_time",
            fake_async_measure_time,
            raising=False,
        )

        result = await _analyze_frames(["frame-a"], "describe", model_adapter=FakeAdapter())

        assert result == "ok"
        assert called["value"] is True

    @pytest.mark.asyncio
    async def test_retries_transient_model_failure(self):
        class FakeAdapter:
            def __init__(self):
                self.calls = 0

            async def invoke(self, messages):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("temporary error")
                return type("Resp", (), {"content": "recovered output"})()

        adapter = FakeAdapter()
        result = await _analyze_frames(
            ["frame-a"],
            "what happened",
            model_adapter=adapter,
            config=VideoUnderstandingConfig(max_retries=3),
        )
        assert result == "recovered output"
        assert adapter.calls == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_permission_or_quota_error(self):
        response = type("Response", (), {"headers": {}, "request": object(), "status_code": 403})()

        class FakeAdapter:
            def __init__(self):
                self.calls = 0

            async def invoke(self, messages):
                self.calls += 1
                raise PermissionDeniedError(
                    "free quota exhausted",
                    response=response,
                    body={"error": {"code": "AllocationQuota.FreeTierOnly"}},
                )

        adapter = FakeAdapter()
        with pytest.raises(PermissionDeniedError):
            await _analyze_frames(
                ["frame-a"],
                "what happened",
                model_adapter=adapter,
                config=VideoUnderstandingConfig(max_retries=3),
            )

        assert adapter.calls == 1


class TestUnifiedAnalyzeVideoFlow:
    @pytest.mark.asyncio
    async def test_analyze_video_segment_passes_generated_prompt_to_model(self, monkeypatch):
        captured = {}

        async def fake_prompt(query, intent=None, context=None):
            return "generated prompt"

        class FakeAdapter:
            async def invoke(self, messages):
                captured["messages"] = messages
                return type("Resp", (), {"content": "plain answer"})()

        monkeypatch.setattr(
            "vsa_agent.tools.video_understanding.generate_understanding_prompt",
            fake_prompt,
        )

        result = await analyze_video_segment(
            frames=["frame-a"],
            query="raw query",
            model_adapter=FakeAdapter(),
        )

        human_message = captured["messages"][1]
        text_part = next(
            part["text"]
            for part in human_message.content
            if part["type"] == "text"
        )
        assert "generated prompt" in text_part
        assert "raw query" not in text_part
        assert result.chunks[0].prompt_used == "generated prompt"

    @pytest.mark.asyncio
    async def test_module_exposes_unified_analyze_video_for_structured_results(self, monkeypatch):
        import vsa_agent.tools.video_understanding as video_understanding_module

        assert hasattr(video_understanding_module, "analyze_video")

        async def fake_analyze_long_video(**kwargs):
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="long structured result",
                chunks=[],
                events=[],
            )

        class FakeCap:
            def isOpened(self):
                return True

            def get(self, prop):
                if prop == 5:
                    return 30.0
                if prop == 7:
                    return 3000
                return 0

            def release(self):
                return None

        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_long_video", fake_analyze_long_video)

        result = await video_understanding_module.analyze_video(
            video_path="video.mp4",
            query="what happened",
        )

        assert isinstance(result, UnderstandingResult)
        assert result.summary_text == "long structured result"

    @pytest.mark.asyncio
    async def test_analyze_video_forwards_time_window_to_long_video_path(self, monkeypatch):
        captured = {}

        async def fake_analyze_long_video(**kwargs):
            captured.update(kwargs)
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="long structured result",
                chunks=[],
                events=[],
                metadata={"chunk_count": 1},
            )

        class FakeCap:
            def isOpened(self):
                return True

            def get(self, prop):
                if prop == 5:
                    return 30.0
                if prop == 7:
                    return 3000
                return 0

            def release(self):
                return None

        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_long_video", fake_analyze_long_video)

        result = await analyze_video(
            video_path="video.mp4",
            query="what happened",
            start_timestamp="PT5S",
            end_timestamp="PT55S",
        )

        assert isinstance(result, UnderstandingResult)
        assert captured["start_timestamp"] == "PT5S"
        assert captured["end_timestamp"] == "PT55S"


class TestVideoUnderstandingToolCompatibility:
    @pytest.mark.asyncio
    async def test_frames_path_returns_legacy_text(self, monkeypatch):
        async def fake_analyze_video_segment(**kwargs):
            return UnderstandingResult(
                query="what happened",
                source_type="video_file",
                summary_text="legacy text output",
                chunks=[],
                events=[],
            )

        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_video_segment", fake_analyze_video_segment)

        result = await video_understanding_tool(frames=["frame-a"], query="what happened")
        assert result == "legacy text output"

    @pytest.mark.asyncio
    async def test_frames_path_forwards_source_type_sensor_and_time_bounds(self, monkeypatch):
        captured = {}

        async def fake_analyze_video_segment(**kwargs):
            captured.update(kwargs)
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="legacy text output",
                chunks=[],
                events=[],
            )

        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_video_segment", fake_analyze_video_segment)

        result = await video_understanding_tool(
            frames=["frame-a"],
            query="what happened",
            source_type="rtsp",
            sensor_id="camera-1",
            start_timestamp="PT5S",
            end_timestamp="PT10S",
        )
        assert result == "legacy text output"
        assert captured["source_type"] == "rtsp"
        assert captured["sensor_id"] == "camera-1"
        assert captured["start_timestamp"] == "PT5S"
        assert captured["end_timestamp"] == "PT10S"

    @pytest.mark.asyncio
    async def test_long_video_path_uses_phase2_pipeline(self, monkeypatch):
        async def fake_analyze_long_video(**kwargs):
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="long video structured result",
                chunks=[],
                events=[],
                metadata={"chunk_count": 1},
            )

        async def fake_summarize_understanding_result(result, query, model_adapter=None):
            return type(
                "Summary",
                (),
                {
                    "text_output": "phase2 long video summary",
                    "structured_output": result,
                },
            )()

        class FakeCap:
            def isOpened(self):
                return True

            def get(self, prop):
                # fps, total_frames => duration 100s
                if prop == 5:  # cv2.CAP_PROP_FPS
                    return 30.0
                if prop == 7:  # cv2.CAP_PROP_FRAME_COUNT
                    return 3000
                return 0

            def release(self):
                return None

        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_long_video", fake_analyze_long_video)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.summarize_understanding_result", fake_summarize_understanding_result)

        result = await video_understanding_tool(video_path="video.mp4", query="what happened")
        assert result == "phase2 long video summary"

    @pytest.mark.asyncio
    async def test_rtsp_local_clip_keeps_long_video_pipeline(self, monkeypatch):
        async def fake_analyze_long_video(**kwargs):
            return UnderstandingResult(
                query=kwargs["query"],
                source_type=kwargs["source_type"],
                summary_text="long video structured result",
                chunks=[],
                events=[],
                metadata={"chunk_count": 1},
            )

        async def fake_summarize_understanding_result(result, query, model_adapter=None):
            return type(
                "Summary",
                (),
                {
                    "text_output": "phase2 long video summary",
                    "structured_output": result,
                },
            )()

        class FakeClient:
            async def get_video_clip(self, sensor_id, start_timestamp, end_timestamp):
                return type("ClipResult", (), {"clip_url": None, "local_path": "C:/tmp/clip.mp4"})()

        class FakeCap:
            def isOpened(self):
                return True

            def get(self, prop):
                if prop == 5:
                    return 30.0
                if prop == 7:
                    return 3000
                return 0

            def release(self):
                return None

        monkeypatch.setattr("vsa_agent.tools.video_understanding._get_vst_client", lambda: FakeClient())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.os.path.exists", lambda _: True)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.cv2.VideoCapture", lambda _: FakeCap())
        monkeypatch.setattr("vsa_agent.tools.video_understanding.analyze_long_video", fake_analyze_long_video)
        monkeypatch.setattr("vsa_agent.tools.video_understanding.summarize_understanding_result", fake_summarize_understanding_result)

        result = await video_understanding_tool(
            video_path="",
            query="what happened",
            source_type="rtsp",
            sensor_id="camera-1",
            start_timestamp="PT5S",
            end_timestamp="PT55S",
        )
        assert result == "phase2 long video summary"
