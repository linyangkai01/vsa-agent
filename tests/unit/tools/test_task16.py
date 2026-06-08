"""Tests for Task 16 — AttributeSearch models and search_by_attributes."""

import asyncio

import pytest

from vsa_agent.tools.attribute_search import AttributeSearchInput
from vsa_agent.tools.attribute_search import AttributeSearchMetadata
from vsa_agent.tools.attribute_search import AttributeSearchResult
from vsa_agent.tools.attribute_search import search_by_attributes


class TestAttributeSearchInput:
    def test_minimal(self):
        inp = AttributeSearchInput(query="person with red hat")
        assert inp.query == "person with red hat"
        assert inp.source_type == "video_file"

    def test_with_list_query(self):
        inp = AttributeSearchInput(query=["red shirt", "blue pants"])
        assert isinstance(inp.query, list)
        assert len(inp.query) == 2


class TestAttributeSearchMetadata:
    def test_all_fields(self):
        m = AttributeSearchMetadata(
            sensor_id="s1", object_id="obj-1", behavior_score=0.8
        )
        assert m.sensor_id == "s1"
        assert m.object_id == "obj-1"
        assert m.behavior_score == pytest.approx(0.8)


class TestSearchByAttributes:
    def test_returns_results(self):
        results = asyncio.run(search_by_attributes("person walking"))
        assert len(results) > 0
        assert isinstance(results[0], AttributeSearchResult)
        assert results[0].metadata.sensor_id != ""
