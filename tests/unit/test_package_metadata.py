import tomllib
from pathlib import Path


def test_package_declares_elasticsearch_async_transport_dependency():
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "elasticsearch[async]>=8.14" in metadata["project"]["dependencies"]
