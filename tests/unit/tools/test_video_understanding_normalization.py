from vsa_agent.data_models.understanding import UnderstandingResult
from vsa_agent.tools import video_understanding
from vsa_agent.tools import video_understanding_normalization as normalization


def _normalize(*, source_type="video_file", raw_output="worker enters", **overrides):
    kwargs = {
        "query": "what happened",
        "source_type": source_type,
        "raw_output": raw_output,
        "prompt_used": "watch carefully",
        "start_timestamp": 5,
        "end_timestamp": "PT10S",
        "thinking": None,
        "time_format": "offset",
    }
    kwargs.update(overrides)
    return normalization._normalize_model_response(**kwargs)


def test_normalization_module_has_no_runtime_io_dependencies():
    assert not hasattr(normalization, "cv2")
    assert not hasattr(normalization, "get_config")
    assert not hasattr(normalization, "write_live_trace_event")


def test_facade_reexports_the_normalization_helpers():
    assert video_understanding._normalize_timestamp is normalization._normalize_timestamp
    assert video_understanding._timestamp_to_seconds is normalization._timestamp_to_seconds
    assert video_understanding._parse_thinking_from_content is normalization._parse_thinking_from_content
    assert video_understanding._normalize_model_response is normalization._normalize_model_response


def test_timestamp_and_reasoning_normalization_are_stable():
    assert normalization._normalize_timestamp(5, time_format="offset") == "PT5S"
    assert normalization._timestamp_to_seconds("PT10S") == 10.0
    assert normalization._parse_thinking_from_content(
        "<thinking>inspect scene</thinking><answer>worker enters</answer>"
    ) == ("inspect scene", "worker enters")


def test_existing_result_is_returned_by_identity():
    existing = UnderstandingResult(
        query="what happened",
        source_type="video_file",
        summary_text="worker enters",
        chunks=[],
        events=[],
    )

    assert _normalize(raw_output=existing) is existing


def test_dictionary_result_receives_query_and_source_defaults():
    result = _normalize(raw_output={"summary_text": "worker enters", "chunks": [], "events": []})

    assert result.query == "what happened"
    assert result.source_type == "video_file"


def test_file_and_rtsp_results_build_source_specific_evidence():
    file_result = _normalize(video_path="video.mp4")
    rtsp_result = _normalize(source_type="rtsp", sensor_id="camera-1")

    file_evidence = file_result.chunks[0].evidence
    assert file_evidence.video_path == "video.mp4"
    assert file_evidence.sensor_id is None

    rtsp_evidence = rtsp_result.chunks[0].evidence
    assert rtsp_evidence.sensor_id == "camera-1"
    assert rtsp_evidence.video_path is None
