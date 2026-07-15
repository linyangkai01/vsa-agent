"""Search Agent - orchestrates search workflow via three-path routing.

Accepts SearchAgentInput, calls tools/search.decompose_query(), then
routes through embed/attribute/fusion search paths.

Matches NVIDIA original where agents/search_agent.py imports
decompose_query + execute_core_search from tools/search.py.
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from vsa_agent.observability.live_trace import write_live_trace_event
from vsa_agent.registry import register_tool
from vsa_agent.tools.incidents import incidents_to_tagged_json, search_output_to_incidents
from vsa_agent.tools.search import (
    DecomposedQuery,
    SearchOutput,
    SearchResult,
    _resolve_search_callable,
    decompose_query,
    should_apply_critic,
)
from vsa_agent.tools.vss_summarize import summarize_search_incidents
from vsa_agent.video_analytics.nvschema import Incident

logger = logging.getLogger(__name__)

# ===== Agent Input Model =====


class SearchAgentInput(BaseModel):
    """Agent-layer input for search requests.

    Mirrors the NVIDIA SearchAgentInput pattern. This wraps the user-facing
    request parameters before query decomposition and search execution.
    """

    query: str = Field(description="Natural language search query")
    agent_mode: bool = Field(default=True, description="Enable LLM query decomposition")
    use_attribute_search: bool | None = Field(
        default=None, description="Enable fusion reranking with attribute search (overrides config if provided)"
    )
    max_results: int = Field(default=5, description="Maximum number of results to return")
    top_k: int | None = Field(default=None, description="Override top_k for embed search")
    video_sources: list[str] = Field(default_factory=list, description="Explicit video filename filters")
    start_time: str | None = Field(default=None, description="Start time filter (ISO format)")
    end_time: str | None = Field(default=None, description="End time filter (ISO format)")
    min_cosine_similarity: float = Field(default=0.0, description="Minimum accepted cosine similarity")
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


class SearchAgentExecutionResult(BaseModel):
    """Internal orchestration result for search QA flow."""

    search_output: SearchOutput
    incidents: list[Incident] = Field(default_factory=list)
    text_answer: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


def _propagate_search_dependency(error: Exception) -> None:
    from vsa_agent.tools.embed_search import SearchDependencyError

    if isinstance(error, SearchDependencyError):
        raise error


def _apply_request_constraints(search_input: SearchAgentInput, decomposed: DecomposedQuery) -> DecomposedQuery:
    return decomposed.model_copy(
        update={
            "video_sources": list(search_input.video_sources or decomposed.video_sources),
            "timestamp_start": search_input.start_time or decomposed.timestamp_start,
            "timestamp_end": search_input.end_time or decomposed.timestamp_end,
            "source_type": search_input.source_type or decomposed.source_type,
            "min_cosine_similarity": max(
                search_input.min_cosine_similarity,
                decomposed.min_cosine_similarity or 0.0,
            ),
        }
    )


def _embed_search_kwargs(decomposed: DecomposedQuery, *, top_k: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"query": decomposed.query, "top_k": top_k}
    optional = {
        "video_sources": decomposed.video_sources or None,
        "timestamp_start": decomposed.timestamp_start,
        "timestamp_end": decomposed.timestamp_end,
        "source_type": decomposed.source_type if decomposed.source_type != "video_file" else None,
        "min_cosine_similarity": decomposed.min_cosine_similarity
        if (decomposed.min_cosine_similarity or 0.0) > 0.0
        else None,
    }
    kwargs.update({key: value for key, value in optional.items() if value is not None})
    return kwargs


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
    incidents = search_output_to_incidents(search_output)
    return incidents_to_tagged_json(incidents)


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
    """Tool wrapper: converts simple args to SearchAgentInput, calls the search QA flow."""
    search_input = SearchAgentInput(query=query, agent_mode=agent_mode, max_results=max_results)
    result = await execute_search_agent_flow(search_input=search_input)
    if result.text_answer:
        return result.text_answer
    if not result.search_output.data:
        return "No matching videos found."
    return _to_incidents_output(result.search_output)


async def _run_search_critic(
    search_input: SearchAgentInput,
    search_output: SearchOutput,
    *,
    config: SearchAgentConfig,
    critic_agent=None,
) -> dict[str, bool | str | None]:
    metadata: dict[str, bool | str | None] = {
        "critic_requested": bool(search_input.use_critic),
        "critic_applied": False,
        "critic_error": None,
    }

    if not search_output.data:
        return metadata

    critic_fn = critic_agent
    if critic_fn is None:
        from vsa_agent.registry import ToolRegistry

        critic_fn = ToolRegistry.get("critic_agent")

    if not should_apply_critic(
        enable_critic=config.enable_critic,
        use_critic=search_input.use_critic,
        critic_agent=critic_fn,
    ):
        return metadata

    videos_data = [
        {"sensor_id": r.sensor_id, "start_timestamp": r.start_time, "end_timestamp": r.end_time}
        for r in search_output.data
    ]
    try:
        critic_result = await critic_fn(
            query=search_input.query,
            videos_json=json.dumps(videos_data),
        )
        metadata["critic_applied"] = True
        logger.info("Critic verification completed: %s", str(critic_result)[:200])
    except Exception as exc:
        metadata["critic_error"] = str(exc)
        logger.warning("Critic verification failed: %s", exc)

    return metadata


def _build_critic_metadata(search_input: SearchAgentInput) -> dict[str, bool | str | None]:
    return {
        "critic_requested": bool(search_input.use_critic),
        "critic_applied": False,
        "critic_error": None,
    }


async def _execute_search_with_metadata(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
    config: SearchAgentConfig | None = None,
    critic_agent=None,
) -> tuple[SearchOutput, dict[str, bool | str | None], DecomposedQuery]:
    """Execute search and return internal critic metadata for orchestration flows."""
    if config is None:
        config = SearchAgentConfig(enable_critic=search_input.use_critic)

    if model_adapter is not None and search_input.agent_mode:
        decomposed = await decompose_query(search_input.query, model_adapter)
    else:
        decomposed = DecomposedQuery(query=search_input.query)
    decomposed = _apply_request_constraints(search_input, decomposed)
    write_live_trace_event(
        "search_agent.decompose_query",
        {"input_query": search_input.query, "decomposed": decomposed},
    )

    has_attributes = bool(decomposed.attributes)
    has_action = decomposed.has_action

    if embed_search is None:
        embed_top_k = search_input.top_k or search_input.max_results
        embed_search = _resolve_search_callable("embed_search", **_embed_search_kwargs(decomposed, top_k=embed_top_k))
    if attribute_search is None and has_attributes:
        attribute_search = _resolve_search_callable(
            "attribute_search",
            attributes=decomposed.attributes,
            top_k=search_input.max_results,
        )

    result = SearchOutput(data=[])

    if not has_action and has_attributes and attribute_search is not None:
        logger.info("Path 1: attribute-only search")
        try:
            results = await attribute_search()
            write_live_trace_event(
                "search_agent.attribute_search",
                {"path": "attribute-only", "attributes": decomposed.attributes, "results": results},
            )
            if isinstance(results, SearchOutput):
                result = results
            elif isinstance(results, list):
                result = SearchOutput(data=results)
            else:
                result = SearchOutput(data=getattr(results, "data", []))
        except Exception as e:
            _propagate_search_dependency(e)
            logger.error("Attribute search failed: %s", e)
            write_live_trace_event(
                "search_agent.attribute_search",
                {"path": "attribute-only", "attributes": decomposed.attributes, "error": str(e)},
            )

    elif not has_attributes and embed_search is not None:
        logger.info("Path 2: embed-only search")
        try:
            results = await embed_search()
            write_live_trace_event(
                "search_agent.embed_search",
                {"path": "embed-only", "query": decomposed.query, "results": results},
            )
            logger.info("search_agent.embed_search path=embed-only query=%r", decomposed.query)
            if isinstance(results, SearchOutput):
                result = results
            elif hasattr(results, "data"):
                result = SearchOutput(data=results.data)
            else:
                result = SearchOutput(data=results if isinstance(results, list) else [])
        except Exception as e:
            _propagate_search_dependency(e)
            logger.error("Embed search failed: %s", e)
            write_live_trace_event(
                "search_agent.embed_search",
                {"path": "embed-only", "query": decomposed.query, "error": str(e)},
            )
            logger.info("search_agent.embed_search path=embed-only status=error query=%r", decomposed.query)

    elif has_action and has_attributes:
        logger.info("Path 3: fusion search")
        embed_results: list[SearchResult] = []
        attr_results: list[SearchResult] = []
        if embed_search is not None:
            try:
                r = await embed_search()
                write_live_trace_event(
                    "search_agent.embed_search",
                    {"path": "fusion", "query": decomposed.query, "results": r},
                )
                embed_results = list(r.data) if hasattr(r, "data") else list(r) if isinstance(r, list) else []
            except Exception as e:
                _propagate_search_dependency(e)
                logger.error("Embed search in fusion failed: %s", e)
                write_live_trace_event(
                    "search_agent.embed_search",
                    {"path": "fusion", "query": decomposed.query, "error": str(e)},
                )
        if attribute_search is not None:
            try:
                r = await attribute_search()
                write_live_trace_event(
                    "search_agent.attribute_search",
                    {"path": "fusion", "attributes": decomposed.attributes, "results": r},
                )
                if isinstance(r, SearchOutput):
                    attr_results = r.data
                elif isinstance(r, list):
                    attr_results = r
                elif hasattr(r, "data"):
                    attr_results = r.data
            except Exception as e:
                _propagate_search_dependency(e)
                logger.error("Attribute search in fusion failed: %s", e)
                write_live_trace_event(
                    "search_agent.attribute_search",
                    {"path": "fusion", "attributes": decomposed.attributes, "error": str(e)},
                )
        merged: dict[str, SearchResult] = {}
        for r in embed_results + attr_results:
            if r.video_name not in merged or r.similarity > merged[r.video_name].similarity:
                merged[r.video_name] = r
        combined = sorted(merged.values(), key=lambda x: x.similarity, reverse=True)
        result = SearchOutput(data=combined)

    metadata = await _run_search_critic(
        search_input,
        result,
        config=config,
        critic_agent=critic_agent,
    )
    return result, metadata, decomposed


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
    search_output, _, _ = await _execute_search_with_metadata(
        search_input=search_input,
        model_adapter=model_adapter,
        embed_search=embed_search,
        attribute_search=attribute_search,
    )
    return search_output


async def execute_search_agent_flow(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
    config: SearchAgentConfig | None = None,
    critic_agent=None,
) -> SearchAgentExecutionResult:
    """Run internal search QA orchestration while preserving public search output."""
    search_output, metadata, decomposed = await _execute_search_with_metadata(
        search_input=search_input,
        model_adapter=model_adapter,
        embed_search=embed_search,
        attribute_search=attribute_search,
        config=config,
        critic_agent=critic_agent,
    )
    metadata = {
        **metadata,
        "decomposed_query": decomposed.query,
        "decomposed_attributes": list(decomposed.attributes),
        "decomposed_has_action": decomposed.has_action,
    }
    incidents = search_output_to_incidents(search_output)
    text_answer = await summarize_search_incidents(incidents, search_input.query)
    write_live_trace_event(
        "search_agent.answer",
        {
            "input_query": search_input.query,
            "text_answer": text_answer,
            "metadata": metadata,
            "search_output": search_output,
        },
    )
    return SearchAgentExecutionResult(
        search_output=search_output,
        incidents=incidents,
        text_answer=text_answer,
        metadata=metadata,
    )
