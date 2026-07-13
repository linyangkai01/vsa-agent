"""Tests for utils/url_translation.py."""

from vsa_agent.utils.url_translation import is_remote_url, normalize_local_path, translate_url


class TestIsRemoteUrl:
    def test_http(self):
        assert is_remote_url("http://example.com/video.mp4") is True

    def test_local_path(self):
        assert is_remote_url("/path/to/video.mp4") is False

    def test_windows_drive_path(self):
        assert is_remote_url("C:/tmp/video.mp4") is False

    def test_rtsp(self):
        assert is_remote_url("rtsp://camera-1/stream") is True


class TestNormalizeLocalPath:
    def test_preserves_windows_drive_style(self):
        assert normalize_local_path("C:\\videos\\demo.mp4") == "C:/videos/demo.mp4"


class TestTranslateUrl:
    def test_local_path_passthrough(self):
        assert translate_url("/path/to/video.mp4") == "/path/to/video.mp4"

    def test_empty_string(self):
        assert translate_url("") == ""

    def test_file_url_maps_to_target_base(self):
        assert translate_url("file:///var/data/video.mp4", target_base="C:/mnt") == "C:/mnt/video.mp4"

    def test_file_url_without_target_base_returns_local_path(self):
        assert translate_url("file:///var/data/video.mp4") == "/var/data/video.mp4"

    def test_s3_url_maps_to_target_base(self):
        assert translate_url("s3://bucket/path/video.mp4", target_base="C:/mnt") == "C:/mnt/bucket/path/video.mp4"

    def test_minio_url_maps_to_target_base(self):
        assert translate_url("minio://bucket/path/video.mp4", target_base="C:/mnt") == "C:/mnt/bucket/path/video.mp4"

    def test_windows_path_passthrough_is_normalized(self):
        assert translate_url("C:\\videos\\demo.mp4") == "C:/videos/demo.mp4"
