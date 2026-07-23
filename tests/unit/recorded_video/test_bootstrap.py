from __future__ import annotations

from copy import deepcopy

import pytest

from vsa_agent.config import (
    AppConfig,
    BackendConfig,
    ProfileConfig,
    RecordedVideoConfig,
    RoleBindingConfig,
    SearchBackendConfig,
)
from vsa_agent.recorded_video.bootstrap import bootstrap_recorded_video_index
from vsa_agent.recorded_video.es_index import INDEX_SETTINGS


class FakeIndices:
    def __init__(self) -> None:
        self.indices: dict[str, dict[str, object]] = {}
        self.aliases: dict[str, str] = {}
        self.created: list[dict[str, object]] = []

    async def exists_alias(self, *, name: str) -> bool:
        return name in self.aliases

    async def exists(self, *, index: str) -> bool:
        return index in self.indices

    async def create(self, *, index: str, settings: dict, mappings: dict):
        self.created.append({"index": index, "settings": deepcopy(settings), "mappings": deepcopy(mappings)})
        self.indices[index] = {"settings": deepcopy(settings), "mappings": deepcopy(mappings)}
        return {"acknowledged": True}

    async def update_aliases(self, *, actions: list[dict[str, object]]):
        add = actions[0]["add"]
        self.aliases[str(add["alias"])] = str(add["index"])
        return {"acknowledged": True}


class FakeClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.indices = FakeIndices()
        self.closed = False

    def options(self, **_kwargs):
        return self

    async def close(self) -> None:
        self.closed = True


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        active_profile="production",
        backends={
            "provider": BackendConfig(
                base_url="https://provider.example/v1",
                api_key_env="PROVIDER_API_KEY",
            )
        },
        profiles={
            "production": ProfileConfig(
                llm=RoleBindingConfig(backend="provider", model="llm"),
                vlm=RoleBindingConfig(backend="provider", model="vlm"),
                embedding=RoleBindingConfig(backend="provider", model="embed-model"),
            )
        },
        search=SearchBackendConfig(
            enabled=True,
            es_endpoint="http://127.0.0.1:9200",
            embed_index="recorded-video-production",
            embedding_dimensions=768,
            verify_certs=False,
            allow_mock_fallback=False,
            force_mock_embedding=False,
        ),
        recorded_video=RecordedVideoConfig(enabled=True, data_root=tmp_path),
    )


@pytest.mark.asyncio
async def test_bootstrap_uses_resolved_embedding_contract_and_closes_client(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VSA_PROFILE", raising=False)
    monkeypatch.setenv("PROVIDER_API_KEY", "secret")
    clients: list[FakeClient] = []

    def client_factory(**kwargs) -> FakeClient:
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    result = await bootstrap_recorded_video_index(_config(tmp_path), client_factory=client_factory)

    assert result.alias == "recorded-video-production"
    assert result.embedding_model == "embed-model"
    assert result.embedding_dimensions == 768
    assert result.created_alias is True
    assert result.index_name.endswith("-v1-d768")
    assert clients[0].kwargs["hosts"] == ["http://127.0.0.1:9200"]
    assert clients[0].indices.created[0]["settings"] == INDEX_SETTINGS
    assert clients[0].closed is True
