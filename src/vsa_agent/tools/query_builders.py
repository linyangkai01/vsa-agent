"""ES query builders — reserved for future Elasticsearch query construction.

⚠️ This module is intentionally empty. The data models (DecomposedQuery,
SearchResult, SearchOutput) have been moved to agents/search_agent.py to
match the NVIDIA original structure where they live inside tools/search.py.

In the NVIDIA original, this file (video_analytics/query_builders.py) contains:
- IncidentQueryBuilder — builds ES {"query": {"bool": {...}}} bodies
- FramesQueryBuilder — builds ES frame-level queries
- BehaviorQueryBuilder — builds ES behavior-level queries

These will be implemented when the ES backend is integrated.
"""
