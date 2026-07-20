from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _production_acceptance_module():
    try:
        return importlib.import_module("vsa_agent.recorded_video.production_acceptance")
    except ModuleNotFoundError:
        pytest.fail("production acceptance module does not exist")


def test_parse_cases_requires_three_distinct_video_hashes(tmp_path: Path) -> None:
    first = tmp_path / "one.mp4"
    second = tmp_path / "two.mp4"
    third = tmp_path / "three.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    third.write_bytes(b"one")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="three distinct video files"):
        module.parse_cases([first, second, third], ["forklift"])


def test_parse_cases_maps_one_query_to_three_distinct_videos(tmp_path: Path) -> None:
    videos = []
    for index, suffix in enumerate((".mp4", ".mp4", ".mkv"), start=1):
        path = tmp_path / f"case-{index}{suffix}"
        path.write_bytes(f"video-{index}".encode())
        videos.append(path)

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, ["forklift near worker"])

    assert [case.path for case in cases] == [path.resolve() for path in videos]
    assert [case.query for case in cases] == ["forklift near worker"] * 3
    assert len({case.sha256 for case in cases}) == 3


def test_parse_cases_maps_three_queries_positionally(tmp_path: Path) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)
    queries = ["forklift", "worker fall", "smoke"]

    module = _production_acceptance_module()
    cases = module.parse_cases(videos, queries)

    assert [case.query for case in cases] == queries


@pytest.mark.parametrize("queries", ([], ["one", "two"], ["  "]))
def test_parse_cases_rejects_invalid_query_cardinality_or_blanks(tmp_path: Path, queries: list[str]) -> None:
    videos = []
    for index in range(3):
        path = tmp_path / f"case-{index}.mp4"
        path.write_bytes(bytes([index + 1]))
        videos.append(path)

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="one or three non-empty queries"):
        module.parse_cases(videos, queries)


def test_parse_cases_rejects_non_file_inputs_with_stable_error(tmp_path: Path) -> None:
    directory = tmp_path / "directory.mp4"
    directory.mkdir()
    second = tmp_path / "second.mp4"
    third = tmp_path / "third.mkv"
    second.write_bytes(b"second")
    third.write_bytes(b"third")

    module = _production_acceptance_module()
    with pytest.raises(ValueError, match="regular readable video files"):
        module.parse_cases([directory, second, third], ["forklift"])
