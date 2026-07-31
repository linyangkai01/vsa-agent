import logging

import pytest

from vsa_agent.privacy.gateway import RemoteProviderGateway
from vsa_agent.privacy.projection import project_ingest_event
from vsa_agent.privacy.schemas import RemoteSafeSearchQuery


@pytest.mark.asyncio
async def test_ingest_gateway_sends_only_canonical_enum_text():
    sent = []
    event = project_ingest_event(
        description="forklift near worker /data/private/alice.mp4",
        tags=("camera-77", "alice@example.com"),
        segment_id="segment-1",
        job_id="job-1",
        start_offset_ms=0,
        end_offset_ms=1000,
    )

    async def sender(text):
        sent.append(text)
        return [0.1]

    result = await RemoteProviderGateway().embed_ingest(event, sender)

    assert result == [0.1]
    assert len(sent) == 1
    assert "forklift_person_proximity" in sent[0]
    assert "/data/private" not in sent[0]
    assert "camera-77" not in sent[0]
    assert "alice@example.com" not in sent[0]


@pytest.mark.asyncio
async def test_search_gateway_logs_metadata_without_query_text(caplog):
    query = RemoteSafeSearchQuery(query="forklift near worker")

    async def sender(text):
        return text

    with caplog.at_level(logging.INFO):
        result = await RemoteProviderGateway().embed_search(query, sender)

    assert result == "forklift near worker"
    assert "query_length=20" in caplog.text
    assert "forklift near worker" not in caplog.text


@pytest.mark.asyncio
async def test_agent_gateway_sends_only_the_screened_current_query():
    query = RemoteSafeSearchQuery(query="forklift near worker")

    class Adapter:
        def __init__(self):
            self.messages = None

        async def invoke(self, messages):
            self.messages = messages
            return "ok"

    adapter = Adapter()
    result = await RemoteProviderGateway().invoke_agent(query, adapter, system_prompt="route tools")

    assert result == "ok"
    assert [message.content for message in adapter.messages] == ["route tools", "forklift near worker"]


def test_gateway_rejects_arbitrary_models_and_dicts():
    gateway = RemoteProviderGateway()

    with pytest.raises(TypeError, match="RemoteSafe"):
        gateway.serialize({"query": "forklift"})
