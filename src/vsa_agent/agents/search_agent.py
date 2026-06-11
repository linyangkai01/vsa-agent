"""Search Agent — orchestrates search workflow via three-path routing.

Accepts SearchAgentInput, calls tools/search.decompose_query(), then
routes through embed/attribute/fusion search paths.

Matches NVIDIA original where agents/search_agent.py imports
decompose_query + execute_core_search from tools/search.py.
"""

import logging

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search import DecomposedQuery
from vsa_agent.tools.search import SearchOutput
from vsa_agent.tools.search import SearchResult
from vsa_agent.tools.search import _resolve_search_callable
from vsa_agent.tools.search import decompose_query

logger = logging.getLogger(__name__)

# ===== Agent Input Model =====


class SearchAgentInput(BaseModel):
    """Agent-layer input for search requests.

    Mirrors the NVIDIA SearchAgentInput pattern. This wraps the user-facing
    request parameters before query decomposition and search execution.
    """

    query: str = Field(description="Natural language search query")
    agent_mode: bool = Field(default=True, description="Enable LLM query decomposition")
    use_attribute_search: bool | None = Field(default=None, description="Enable fusion reranking with attribute search (overrides config if provided)")
    max_results: int = Field(default=5, description="Maximum number of results to return")
    top_k: int | None = Field(default=None, description="Override top_k for embed search")
    start_time: str | None = Field(default=None, description="Start time filter (ISO format)")
    end_time: str | None = Field(default=None, description="End time filter (ISO format)")
    source_type: str = Field(default="video_file", description="Type of video source: video_file or rtsp")
    use_critic: bool = Field(default=True, description="Whether to verify search results with VLM critic agent")


class SearchAgentConfig(BaseModel):
    """Configuration for the search agent. Mirrors NVIDIA SearchAgentConfig."""

    embed_search_tool: str = Field(default="embed_search")
    attribute_search_tool: str | None = Field(default=None)
    agent_mode_llm: str | None = Field(default=None)
    use_attribute_search: bool = Field(default=False)
    default_max_results: int = Field(default=10)
    embed_confidence_threshold: float = Field(default=0.1)
    enable_critic: bool = Field(default=False)
    search_max_iterations: int = Field(default=1, ge=1)


# ===== Presentation Converters =====


def _to_search_results(raw: list) -> list:
    """Convert raw results to SearchResult list. Mirrors NVIDIA _to_search_results."""
    out = []
    for r in raw:
        if isinstance(r, SearchResult):
            out.append(r)
        elif hasattr(r, "model_dump"):
            d = r.model_dump()
            d.setdefault("similarity", d.pop("similarity_score", 0.0))
            d.setdefault("object_ids", [])
            out.append(SearchResult(**d))
        elif isinstance(r, dict) and not hasattr(r, "model_dump"):
            d = dict(r)
            d.setdefault("description", d.get("description", ""))
            d.setdefault("start_time", d.get("start_time", ""))
            d.setdefault("end_time", d.get("end_time", ""))
            d.setdefault("sensor_id", d.get("sensor_id", ""))
            d.setdefault("screenshot_url", d.get("screenshot_url", ""))
            d.setdefault("similarity", d.get("similarity_score", d.get("similarity", 0.0)))
            d.setdefault("object_ids", d.get("object_ids", []))
            d.setdefault("video_name", d.get("video_name", ""))
            out.append(SearchResult(**d))
    return out


def _to_incidents_output(search_output) -> str:
    """Format SearchOutput as incidents JSON. Mirrors NVIDIA _to_incidents_output."""
    import json
    incidents = []
    for result in (search_output.data if hasattr(search_output, "data") else search_output):
        try:
            name = getattr(result, "video_name", "unknown")
            desc = getattr(result, "description", "")
            sim = getattr(result, "similarity", 0.0)
            start = getattr(result, "start_time", "")
            end = getattr(result, "end_time", "")
            incident = {
                "Alert Details": {
                    "Alert Triggered": name,
                    "video_description": desc,
                    "similarity_score": round(sim, 2),
                    "description": desc,
                },
                "Clip Information": {
                    "Timestamp": start,
                    "video_id": name,
                    "start_time": start,
                    "end_time": end,
                },
            }
            incidents.append(incident)
        except Exception:
            continue
    return "<incidents>\n" + json.dumps({"incidents": incidents}, indent=2) + "\n</incidents>"



# ===== Three-Path Routing =====

# ===== Registered Tool Wrapper =====


@register_tool(
    "search_agent",
    description="Search for video clips matching a description. "
                "Three-path routing: embed-only, attribute-only, or fusion.",
)
async def search_agent_tool(
    query: str,
    agent_mode: bool = True,
    max_results: int = 5,
) -> str:
    """Tool wrapper: converts simple args to SearchAgentInput, calls execute_search."""
    search_input = SearchAgentInput(query=query, agent_mode=agent_mode, max_results=max_results)
    result = await execute_search(search_input=search_input)
    # Convert SearchOutput to readable string for LLM
    if not result.data:
        return "No matching videos found."
    lines = [f"Found {len(result.data)} result(s):"]
    for r in result.data:
        lines.append(
            f"- {r.video_name} (similarity: {r.similarity:.2f}, "
            f"time: {r.start_time} to {r.end_time})"
        )
    return "\n".join(lines)



async def execute_search(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """Execute search with query decomposition and three-path routing.

    Decomposes the query via LLM (tools/search.decompose_query), then routes
    through one of three paths:
    - Path 1: attribute-only (has_action=False, attributes present)
    - Path 2: embed-only (no attributes)
    - Path 3: fusion (has_action=True, attributes present)
    """
    if model_adapter is not None and search_input.agent_mode:
        decomposed = await decompose_query(search_input.query, model_adapter)
    else:
        decomposed = DecomposedQuery(query=search_input.query)

    has_attributes = bool(decomposed.attributes)
    has_action = decomposed.has_action

    if embed_search is None:
        embed_search = _resolve_search_callable("embed_search", query=decomposed.query)
    if attribute_search is None and has_attributes:
        attribute_search = _resolve_search_callable("attribute_search", attributes=decomposed.attributes)

    if not has_action and has_attributes and attribute_search is not None:
        logger.info("Path 1: attribute-only search")
        try:
            results = await attribute_search()
            if isinstance(results, SearchOutput):
                return results
            if isinstance(results, list):
                return SearchOutput(data=results)
            return SearchOutput(data=getattr(results, "data", []))
        except Exception as e:
            logger.error("Attribute search failed: %s", e)
            return SearchOutput(data=[])

    if not has_attributes and embed_search is not None:
        logger.info("Path 2: embed-only search")
        try:
            results = await embed_search()
            if isinstance(results, SearchOutput):
                return results
            if hasattr(results, "data"):
                return SearchOutput(data=results.data)
            return SearchOutput(data=results if isinstance(results, list) else [])
        except Exception as e:
            logger.error("Embed search failed: %s", e)
            return SearchOutput(data=[])

    if has_action and has_attributes:
        logger.info("Path 3: fusion search")
        embed_results: list[SearchResult] = []
        attr_results: list[SearchResult] = []
        if embed_search is not None:
            try:
                r = await embed_search()
                embed_results = list(r.data) if hasattr(r, "data") else list(r) if isinstance(r, list) else []
            except Exception as e:
                logger.error("Embed search in fusion failed: %s", e)
        if attribute_search is not None:
            try:
                r = await attribute_search()
                if isinstance(r, SearchOutput):
                    attr_results = r.data
                elif isinstance(r, list):
                    attr_results = r
                elif hasattr(r, "data"):
                    attr_results = r.data
            except Exception as e:
                logger.error("Attribute search in fusion failed: %s", e)
        merged: dict[str, SearchResult] = {}
        for r in embed_results + attr_results:
            if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
                merged[r.video_name] = r
        combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
        result = SearchOutput(data=combined)

        # Optional: run critic verification if critic_agent is registered
        try:
            from vsa_agent.registry import ToolRegistry
            critic_fn = ToolRegistry.get("critic_agent")
            if critic_fn and combined:
                import json as json_
                videos_data = [
                    {"sensor_id": r.sensor_id, "start_timestamp": r.start_time, "end_timestamp": r.end_time}
                    for r in combined
                ]
                critic_result = await critic_fn(
                    query=search_input.query,
                    videos_json=json_.dumps(videos_data),
                )
                logger.info("Critic verification completed: %s", str(critic_result)[:200])
        except Exception:
            pass  # Critic is optional; failure doesn't block search

        return result

    return SearchOutput(data=[])
