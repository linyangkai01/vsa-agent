"""Tests for tools/attribute_search.py."""

from vsa_agent.tools.attribute_search import (
    AttributeSearchInput,
    AttributeSearchMetadata,
    AttributeSearchResult,
    search_by_attributes,
)
from vsa_agent.tools.search import SearchResult


class TestAttributeSearchInput:
    def test_required_fields(self):
        inp = AttributeSearchInput(query="person in red shirt")
        assert inp.query == "person in red shirt"
        assert inp.top_k == 1


class TestAttributeSearchMetadata:
    def test_required_fields(self):
        meta = AttributeSearchMetadata(sensor_id="s1", object_id="obj1")
        assert meta.sensor_id == "s1"


class TestAttributeSearchResult:
    def test_required_fields(self):
        meta = AttributeSearchMetadata(sensor_id="s1", object_id="obj1")
        result = AttributeSearchResult(metadata=meta)
        assert result.metadata.sensor_id == "s1"


class TestSearchByAttributes:
    async def test_returns_list(self):
        result = await search_by_attributes(query_text="person in red shirt")
        assert isinstance(result, list)


class TestDeduplicateByVideoName:
    def test_deduplicates(self):
        from vsa_agent.tools.attribute_search import _deduplicate_by_video_name

        results = [
            SearchResult(
                video_name="v1", description="d1", start_time="t1", end_time="t2", sensor_id="s1", similarity=0.9
            ),
            SearchResult(
                video_name="v1", description="d1", start_time="t1", end_time="t2", sensor_id="s1", similarity=0.7
            ),
        ]
        deduped = _deduplicate_by_video_name(results)
        assert len(deduped) == 1
        assert deduped[0].similarity == 0.9


class TestDeduplicateByObject:
    def test_keeps_highest_object_score(self):
        from vsa_agent.tools.attribute_search import _deduplicate_by_object

        low = AttributeSearchResult(
            metadata=AttributeSearchMetadata(
                sensor_id="s1",
                object_id="obj1",
                behavior_score=0.4,
                video_name="v1",
            )
        )
        high = AttributeSearchResult(
            metadata=AttributeSearchMetadata(
                sensor_id="s1",
                object_id="obj1",
                behavior_score=0.8,
                video_name="v1",
            )
        )
        deduped = _deduplicate_by_object([low, high])
        assert len(deduped) == 1
        assert deduped[0].metadata.behavior_score == 0.8


class TestMultiAttributeMerge:
    def test_fuse_multi_attribute_requires_all_attributes(self):
        from vsa_agent.tools.attribute_search import _fuse_multi_attribute

        grouped = {
            "attr1": [
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(sensor_id="s1", object_id="o1", video_name="v1")
                ),
            ],
            "attr2": [
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(sensor_id="s1", object_id="o2", video_name="v1")
                ),
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(sensor_id="s2", object_id="o3", video_name="v2")
                ),
            ],
        }
        fused = _fuse_multi_attribute(["attr1", "attr2"], grouped)
        assert len(fused) == 2
        assert all(item.metadata.video_name == "v1" for item in fused)

    def test_fuse_multi_attribute_does_not_confuse_two_objects_from_one_attribute(self):
        from vsa_agent.tools.attribute_search import _fuse_multi_attribute

        grouped = {
            "attr1": [
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(sensor_id="s1", object_id="o1", video_name="v1")
                ),
                AttributeSearchResult(
                    metadata=AttributeSearchMetadata(sensor_id="s1", object_id="o2", video_name="v1")
                ),
            ],
            "attr2": [],
        }
        fused = _fuse_multi_attribute(["attr1", "attr2"], grouped)
        assert fused == []

    def test_append_multi_attribute_returns_union(self):
        from vsa_agent.tools.attribute_search import _append_multi_attribute

        grouped = {
            "attr1": [
                AttributeSearchResult(metadata=AttributeSearchMetadata(sensor_id="s1", object_id="o1", video_name="v1"))
            ],
            "attr2": [
                AttributeSearchResult(metadata=AttributeSearchMetadata(sensor_id="s2", object_id="o2", video_name="v2"))
            ],
        }
        appended = _append_multi_attribute(["attr1", "attr2"], grouped)
        assert len(appended) == 2


class TestFrameLookup:
    async def test_perform_frame_lookups_enriches_metadata(self):
        from vsa_agent.tools.attribute_search import _perform_frame_lookups

        class FakeES:
            async def search(self, index, body):
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
                                    "score": 0.91,
                                    "timestamp": "2025-01-01T10:00:01Z",
                                }
                            }
                        ]
                    }
                }

        raw = AttributeSearchResult(
            metadata=AttributeSearchMetadata(
                sensor_id="s1",
                object_id="o1",
                frame_timestamp="2025-01-01T10:00:00Z",
                behavior_score=0.7,
                video_name="v1",
            )
        )
        enriched = await _perform_frame_lookups([raw], FakeES(), "frames-index")
        assert len(enriched) == 1
        assert enriched[0].metadata.bbox == {"x": 1, "y": 2, "w": 3, "h": 4}
        assert enriched[0].metadata.frame_score == 0.91


class TestFallbackBehavior:
    async def test_attribute_search_tool_uses_store_when_es_path_returns_no_results(self, monkeypatch):
        from vsa_agent.tools.attribute_search import attribute_search_tool
        from vsa_agent.tools.search import SearchOutput

        async def fake_search_attributes(search_input, allow_mock_fallback=True):
            assert allow_mock_fallback is False
            return []

        class FakeStore:
            async def search_by_attributes(self, attributes, top_k):
                return SearchOutput(
                    data=[
                        SearchResult(
                            video_name="store-v1",
                            description="store result",
                            start_time="t1",
                            end_time="t2",
                            sensor_id="s1",
                            similarity=0.8,
                        )
                    ]
                )

        monkeypatch.setattr("vsa_agent.tools.attribute_search.search_attributes", fake_search_attributes)

        output = await attribute_search_tool(["person"], store=FakeStore(), top_k=5)
        assert len(output.data) == 1
        assert output.data[0].video_name == "store-v1"

    async def test_search_by_attributes_uses_shared_search_config(self, monkeypatch):
        from vsa_agent.config import AppConfig, SearchBackendConfig

        class FakeIndices:
            async def exists(self, index):
                assert index == "real-behavior"
                return True

        class FakeES:
            def __init__(self, endpoint):
                assert endpoint == "http://es:9200"
                self.indices = FakeIndices()
                self.closed = False

            async def search(self, index, body):
                assert index == "real-behavior"
                return {
                    "hits": {
                        "hits": [
                            {
                                "_score": 0.86,
                                "_source": {
                                    "sensor_id": "cam-1",
                                    "object_id": "person-1",
                                    "object_type": "person",
                                    "timestamp": "2026-07-03T08:00:00Z",
                                    "end": "2026-07-03T08:00:05Z",
                                    "video_name": "site-a.mp4",
                                },
                            }
                        ]
                    }
                }

            async def close(self):
                self.closed = True

        monkeypatch.setattr(
            "vsa_agent.config.get_config",
            lambda: AppConfig(
                search=SearchBackendConfig(
                    enabled=True,
                    es_endpoint="http://es:9200",
                    behavior_index="real-behavior",
                    frames_index="real-frames",
                )
            ),
        )
        monkeypatch.setattr("vsa_agent.tools.attribute_search.AsyncElasticsearch", FakeES)

        results = await search_by_attributes("person", allow_mock_fallback=False)

        assert len(results) == 1
        assert results[0].metadata.video_name == "site-a.mp4"
