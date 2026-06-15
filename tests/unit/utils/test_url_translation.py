"""Tests for utils/url_translation.py."""
from vsa_agent.utils.url_translation import translate_url, is_remote_url

class TestIsRemoteUrl:
    def test_http(self):
        assert is_remote_url("http://example.com/video.mp4") is True
    def test_local_path(self):
        assert is_remote_url("/path/to/video.mp4") is False
    def test_windows_drive_path(self):
        assert is_remote_url("C:/tmp/video.mp4") is False

class TestTranslateUrl:
    def test_local_path_passthrough(self):
        assert translate_url("/path/to/video.mp4") == "/path/to/video.mp4"
    def test_empty_string(self):
        assert translate_url("") == ""
    def test_file_url_maps_to_target_base(self):
        assert translate_url("file:///var/data/video.mp4", target_base="C:/mnt") == "C:/mnt/video.mp4"
    def test_s3_url_maps_to_target_base(self):
        assert translate_url("s3://bucket/path/video.mp4", target_base="C:/mnt") == "C:/mnt/bucket/path/video.mp4"
    def test_minio_url_maps_to_target_base(self):
        assert translate_url("minio://bucket/path/video.mp4", target_base="C:/mnt") == "C:/mnt/bucket/path/video.mp4"
