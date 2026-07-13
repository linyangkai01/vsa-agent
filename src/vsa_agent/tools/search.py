"""Core search — data models, query decomposition, and three-path routing.

Matches the NVIDIA original structure where data models (DecomposedQuery,
SearchResult, SearchOutput), decompose_query(), and the core search
function all live inside tools/search.py (~1400 lines).

Design Pattern: #13 Three-Path Search Strategy.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from vsa_agent.registry import register_tool
from vsa_agent.tools.search_pipeline import (
    filter_rejected_sensors,
    max_similarity,
    normalize_search_results,
    rank_unique_results,
    select_fusion_results,
    select_search_route,
    should_apply_critic,
    trim_search_results,
)

logger = logging.getLogger(__name__)

# ===== Data Models =====
# These match the NVIDIA original where DecomposedQuery/SearchResult/SearchOutput
# are defined directly in tools/search.py.


class DecomposedQuery(BaseModel):
    """Structured search parameters extracted from a natural language query."""

    query: str = Field(default="", description="The main search description")
    video_sources: list[str] = Field(default_factory=list, description="List of video source names")
    source_type: str = Field(default="video_file", description="rtsp or video_file")
    timestamp_start: str | None = Field(default=None, description="Start timestamp ISO format")
    timestamp_end: str | None = Field(default=None, description="End timestamp ISO format")
    attributes: list[str] = Field(default_factory=list, description="Person/object attributes to filter by")
    has_action: bool | None = Field(default=None, description="True if query contains an action/event/activity")
    top_k: int | None = Field(default=None, description="Number of results to return")
    min_cosine_similarity: float | None = Field(default=None, description="Minimum similarity threshold")


class SearchResult(BaseModel):
    """A single search result item matching the query."""

    video_name: str = Field(..., description="Name of the video file")
    description: str = Field(..., description="Description of the video content")
    start_time: str = Field(..., description="Start time ISO timestamp")
    end_time: str = Field(..., description="End time ISO timestamp")
    sensor_id: str = Field(..., description="Sensor identifier")
    screenshot_url: str = Field(default="", description="URL to screenshot")
    similarity: float = Field(..., description="Cosine similarity score (0.0-1.0)")
    object_ids: list[str] = Field(default_factory=list, description="Tracked object IDs")


class SearchOutput(BaseModel):
    """Container for a list of search results."""

    data: list[SearchResult] = Field(default_factory=list, description="List of search results matching the query")


# ===== Configuration =====


class SearchConfig(BaseModel):
    """Configuration for the search tool. Mirrors NVIDIA SearchConfig fields."""

    embed_search_tool: str = Field(default="embed_search")
    attribute_search_tool: str | None = Field(default=None)
    embed_confidence_threshold: float = Field(default=0.2)
    agent_mode_llm: str | None = Field(default=None)
    use_attribute_search: bool = Field(default=False)
    default_max_results: int = Field(default=10)
    fusion_method: str = Field(default="rrf")
    w_embed: float = Field(default=0.35)
    w_attribute: float = Field(default=0.55)
    rrf_k: int = Field(default=60)
    rrf_w: float = Field(default=0.5)
    enable_critic: bool = Field(default=False, description="Enable VLM critic verification of results")
    search_max_iterations: int = Field(default=1, ge=1, description="Max search iterations when refining with critic")


class SearchInput(BaseModel):
    """Input for the search tool. Mirrors NVIDIA SearchInput fields."""

    model_config = {"extra": "forbid"}

    query: str = Field(..., description="Description of the item to search from")
    source_type: str = Field(default="video_file", description="rtsp or video_file")
    video_sources: list[str] | None = Field(default=None)
    description: str | None = Field(default=None)
    timestamp_start: str | None = Field(default=None)
    timestamp_end: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    min_cosine_similarity: float = Field(default=0.0, description="Minimum cosine similarity filter")
    use_critic: bool = Field(default=False, description="Whether to verify results with VLM critic")
    agent_mode: bool = Field(default=True)


# ===== Core Search (async generator) =====


async def execute_core_search(
    search_input: SearchInput,
    embed_search,
    agent_llm=None,
    config: SearchConfig | None = None,
    attribute_search_fn=None,
    critic_agent=None,
):
    """Core search with three-path routing, confidence threshold, and critic verification.

    Yields AgentMessageChunk for progress updates, then SearchOutput as final result.
    """
    from vsa_agent.agents.data_models import AgentMessageChunk, AgentMessageChunkType

    if config is None:
        config = SearchConfig()
    top_k = search_input.top_k if search_input.top_k is not None else config.default_max_results
    original_top_k = top_k

    if search_input.agent_mode and agent_llm is not None:
        decomposed = await decompose_query(search_input.query, agent_llm)
        attributes = decomposed.attributes
        has_action = decomposed.has_action
    else:
        attributes = []
        has_action = None
    route = select_search_route(
        has_action,
        attributes,
        attribute_available=attribute_search_fn is not None,
    )

    rejected_results = set()
    iteration_num = 0
    do_search = True
    search_results = []

    while do_search and iteration_num < config.search_max_iterations:
        iteration_num += 1

        if route == "attribute":
            logger.info("Path 1: attribute-only search")
            try:
                results = await attribute_search_fn()
                search_results = normalize_search_results(results)
                yield AgentMessageChunk(
                    type=AgentMessageChunkType.THOUGHT,
                    content=f"Attribute search returned {len(search_results)} results",
                )
            except Exception as e:
                logger.error("Attribute search failed: %s", e)

        elif route == "embed":
            logger.info("Path 2: embed-only search")
            try:
                results = await embed_search()
                search_results = normalize_search_results(results)
                yield AgentMessageChunk(
                    type=AgentMessageChunkType.THOUGHT, content=f"Embed search returned {len(search_results)} results"
                )
                if config.embed_confidence_threshold > 0:
                    max_score = max_similarity(search_results)
                    if max_score is not None and max_score < config.embed_confidence_threshold:
                        yield AgentMessageChunk(
                            type=AgentMessageChunkType.THOUGHT,
                            content=f"Embed confidence {max_score:.3f} below threshold",
                        )
            except Exception as e:
                logger.error("Embed search failed: %s", e)

        elif route == "fusion":
            logger.info("Path 3: fusion search")
            embed_results = []
            attr_results_list = []
            try:
                embed_results = normalize_search_results(await embed_search())
            except Exception as e:
                logger.error("Embed in fusion failed: %s", e)
            if attribute_search_fn is not None:
                try:
                    attr_results_list = normalize_search_results(await attribute_search_fn())
                except Exception as e:
                    logger.error("Attribute in fusion failed: %s", e)
            search_results = select_fusion_results(
                embed_results,
                attr_results_list,
                confidence_threshold=config.embed_confidence_threshold,
            )
            yield AgentMessageChunk(
                type=AgentMessageChunkType.THOUGHT, content=f"Fusion search returned {len(search_results)} results"
            )

        if (
            should_apply_critic(
                enable_critic=config.enable_critic,
                use_critic=search_input.use_critic,
                critic_agent=critic_agent,
            )
            and search_results
        ):
            try:
                from vsa_agent.agents.critic_agent import CriticAgentInput, CriticAgentResult, VideoInfo

                yield AgentMessageChunk(
                    type=AgentMessageChunkType.THOUGHT, content=f"Verifying {len(search_results)} results with critic"
                )
                search_videos = [
                    VideoInfo(sensor_id=r.sensor_id, start_timestamp=r.start_time, end_timestamp=r.end_time)
                    for r in search_results
                ]
                critic_input = CriticAgentInput(query=search_input.query, videos=search_videos)
                critic_output = await critic_agent(critic_input)
                new_confirmed = 0
                new_rejected = 0
                for vr in critic_output.video_results:
                    if vr.result == CriticAgentResult.CONFIRMED:
                        new_confirmed += 1
                    elif vr.result == CriticAgentResult.REJECTED:
                        rejected_results.add(vr.video_info)
                        new_rejected += 1
                        top_k += 1
                        do_search = True
                yield AgentMessageChunk(
                    type=AgentMessageChunkType.THOUGHT,
                    content=f"Critic: {new_confirmed} confirmed, {new_rejected} rejected",
                )
                search_results = filter_rejected_sensors(search_results, rejected_results)
            except Exception as e:
                logger.error("Critic verification failed: %s", e)

        if not should_apply_critic(
            enable_critic=config.enable_critic,
            use_critic=search_input.use_critic,
            critic_agent=critic_agent,
        ):
            do_search = False

    yield SearchOutput(data=trim_search_results(search_results, original_top_k))


# ===== Constants =====

DECOMPOSITION_SYSTEM_PROMPT = (
    "You are a search query analyzer. Extract structured search parameters "
    "from natural language queries. Return ONLY valid JSON, no commentary."
)

DECOMPOSITION_USER_TEMPLATE = """Extract structured search parameters from this query.

Available fields:
- query: The main search description including actions AND attributes
- attributes: List of person/object descriptions only, not just "person"
- has_action: True if query mentions an action/event (walking, running, carrying, etc.). \
False if only visual attributes (what something LOOKS LIKE).
- top_k: Number of results (integer, only if explicitly mentioned like "top 5")
- video_sources: Video names mentioned (empty list if none)

Examples:
"person walking" -> {"query": "person walking", "attributes": ["person"], "has_action": true}
"red car" -> {"query": "red car", "has_action": false}
"find person in blue jacket running, top 3" -> \
{"query": "person in blue jacket running", "attributes": ["person in blue jacket"], "has_action": true, "top_k": 3}
"forklift in warehouse" -> {"query": "forklift in warehouse", "has_action": false}

User query: __USER_QUERY__"""


# ===== Query Decomposition =====
# Matches NVIDIA decompose_query() in tools/search.py (same function signature).


async def decompose_query(user_query: str, model_adapter) -> DecomposedQuery:
    """Decompose a natural language query into structured search parameters."""
    user_prompt = DECOMPOSITION_USER_TEMPLATE.replace("__USER_QUERY__", user_query)
    messages = [
        SystemMessage(content=DECOMPOSITION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    try:
        response = await model_adapter.invoke(messages)
        content = str(response.content) if response.content is not None else ""
        content = content.replace(chr(92) + "n", chr(10))
        text = content.strip()
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip() if end != -1 else text[start:].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip() if end != -1 else text[start:].strip()
        extracted = json.loads(text)
        return DecomposedQuery(
            query=extracted.get("query", user_query),
            video_sources=extracted.get("video_sources", []) or [],
            source_type=extracted.get("source_type", "video_file") or "video_file",
            timestamp_start=extracted.get("timestamp_start"),
            timestamp_end=extracted.get("timestamp_end"),
            attributes=extracted.get("attributes", []) or [],
            has_action=extracted.get("has_action"),
            top_k=extracted.get("top_k"),
            min_cosine_similarity=extracted.get("min_cosine_similarity"),
        )
    except Exception as e:
        logger.warning("Failed to decompose query, using raw input: %s", e)
        return DecomposedQuery(query=user_query)


# ===== Fusion Algorithms (Phase A) =====


def attribute_result_to_search_result(
    attr_result,
    video_name=None,
    description="",
):
    """Convert AttributeSearchResult to SearchResult. Matches NVIDIA original.

    Uses frame_score if available (>0), otherwise behavior_score.
    Uses start_time/end_time from metadata, falling back to frame_timestamp.
    """
    from vsa_agent.tools.attribute_search import AttributeSearchResult

    if isinstance(attr_result, dict):
        validated = AttributeSearchResult.model_validate(attr_result)
    elif isinstance(attr_result, AttributeSearchResult):
        validated = attr_result
    else:
        validated = AttributeSearchResult.model_validate(attr_result)

    metadata = validated.metadata
    similarity = (
        float(metadata.frame_score)
        if (metadata.frame_score is not None and metadata.frame_score > 0.0)
        else float(metadata.behavior_score)
    )
    start_time = metadata.start_time or metadata.frame_timestamp
    end_time = metadata.end_time or metadata.frame_timestamp
    result_video_name = video_name or metadata.video_name or metadata.sensor_id
    if not description:
        description = f"Attribute match at {metadata.frame_timestamp}"

    return SearchResult(
        video_name=result_video_name,
        description=description,
        start_time=start_time,
        end_time=end_time,
        sensor_id=metadata.sensor_id,
        screenshot_url=validated.screenshot_url or "",
        similarity=similarity,
        object_ids=[str(metadata.object_id)],
    )


def _apply_weighted_linear_fusion(video_data, w_embed, w_attribute):
    """Weighted linear fusion: (w_embed * embed_score) + (w_attribute * normalised_attribute_score).

    Returns list of SearchResult sorted by fusion score descending.
    """
    reranked = []
    for video in video_data:
        fusion_score = w_embed * video["embed_score"] + w_attribute * video["normalised_attribute_score"]
        er = video["embed_result"]
        reranked.append(
            (
                fusion_score,
                SearchResult(
                    video_name=er.video_name,
                    description=er.description,
                    start_time=er.start_time,
                    end_time=er.end_time,
                    sensor_id=er.sensor_id,
                    screenshot_url=video.get("screenshot_url", ""),
                    similarity=fusion_score,
                    object_ids=video.get("object_ids", []),
                ),
            )
        )
    reranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in reranked]


def _apply_rrf_fusion(video_data, rrf_k, rrf_w):
    """Reciprocal Rank Fusion: 1/(rank_embed + k) + w * normalised_attribute_score.

    Sorts by embed_score descending to determine rank, then applies RRF.
    Returns list of SearchResult sorted by RRF score descending.
    """
    sorted_data = sorted(video_data, key=lambda x: x["embed_score"], reverse=True)
    reranked = []
    for rank, video in enumerate(sorted_data, start=1):
        rrf_score = 1.0 / (rank + rrf_k) + rrf_w * video["normalised_attribute_score"]
        er = video["embed_result"]
        reranked.append(
            (
                rrf_score,
                SearchResult(
                    video_name=er.video_name,
                    description=er.description,
                    start_time=er.start_time,
                    end_time=er.end_time,
                    sensor_id=er.sensor_id,
                    screenshot_url=video.get("screenshot_url", ""),
                    similarity=rrf_score,
                    object_ids=video.get("object_ids", []),
                ),
            )
        )
    reranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in reranked]


def _apply_rrf_fusion_with_attribute_rank(video_data, rrf_k, rrf_w):
    """RRF using both embed and attribute ranks: 1/(rank_embed + k) + w * 1/(rank_attribute + k).

    Sorts by both scores independently to determine ranks.
    Returns list of SearchResult sorted by RRF score descending.
    """
    sorted_by_embed = sorted(video_data, key=lambda x: x["embed_score"], reverse=True)
    embed_ranks = {id(v): rank for rank, v in enumerate(sorted_by_embed, start=1)}
    sorted_by_attr = sorted(video_data, key=lambda x: x["normalised_attribute_score"], reverse=True)
    attr_ranks = {id(v): rank for rank, v in enumerate(sorted_by_attr, start=1)}

    reranked = []
    for video in video_data:
        rank_embed = embed_ranks[id(video)]
        rank_attribute = attr_ranks[id(video)]
        rrf_score = 1.0 / (rank_embed + rrf_k) + rrf_w * (1.0 / (rank_attribute + rrf_k))
        er = video["embed_result"]
        reranked.append(
            (
                rrf_score,
                SearchResult(
                    video_name=er.video_name,
                    description=er.description,
                    start_time=er.start_time,
                    end_time=er.end_time,
                    sensor_id=er.sensor_id,
                    screenshot_url=video.get("screenshot_url", ""),
                    similarity=rrf_score,
                    object_ids=video.get("object_ids", []),
                ),
            )
        )
    reranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in reranked]


async def fusion_search_rerank(
    embed_results,
    attributes,
    attribute_search_fn,
    fusion_method="rrf",
    rrf_k=60,
    rrf_w=0.5,
    w_attribute=0.55,
    w_embed=0.35,
    source_type="video_file",
):
    """Rerank embed results using fusion with attribute search.

    For each embed result:
    1. Run attribute_search for each attribute
    2. Compute normalised_attribute_score
    3. Apply fusion method (weighted_linear, rrf, or rrf_with_attribute_rank)
    """
    video_data = []
    for embed_result in embed_results:
        try:
            attr_results = await attribute_search_fn()
            attr_list = normalize_search_results(attr_results)

            search_results = []
            for ar in attr_list:
                try:
                    sr = attribute_result_to_search_result(ar)
                    search_results.append(sr)
                except Exception:
                    continue

            attr_count = len(attributes) if attributes else 1
            if search_results:
                attr_score_sum = sum(r.similarity for r in search_results)
                normalised_attr_score = attr_score_sum / attr_count
            else:
                normalised_attr_score = 0.0

            video_data.append(
                {
                    "embed_result": embed_result,
                    "embed_score": embed_result.similarity,
                    "normalised_attribute_score": normalised_attr_score,
                    "screenshot_url": "",
                    "object_ids": embed_result.object_ids or [],
                }
            )
        except Exception:
            continue

    if fusion_method == "weighted_linear":
        return _apply_weighted_linear_fusion(video_data, w_embed, w_attribute)
    elif fusion_method == "rrf":
        return _apply_rrf_fusion(video_data, rrf_k, rrf_w)
    elif fusion_method == "rrf_with_attribute_rank":
        return _apply_rrf_fusion_with_attribute_rank(video_data, rrf_k, rrf_w)
    else:
        raise ValueError(
            f"Unknown fusion_method: {fusion_method}. Must be 'weighted_linear', 'rrf', or 'rrf_with_attribute_rank'"
        )


async def _run_attribute_only_search(
    attributes,
    attribute_search_fn,
    top_k=10,
    source_type="video_file",
):
    """Run attribute-only search and convert results to SearchResult.

    Filters single-word attributes (like NVIDIA _is_single_word).
    """
    if not attributes:
        return []

    attr_results = await attribute_search_fn()
    result_list = normalize_search_results(attr_results)

    search_results = []
    for ar in result_list:
        try:
            sr = attribute_result_to_search_result(ar)
            search_results.append(sr)
        except Exception:
            continue

    search_results.sort(key=lambda x: x.similarity, reverse=True)
    return search_results[:top_k]


# ===== Helper =====


def _resolve_search_callable(tool_name: str, **kwargs):
    """Resolve a search tool from the registry when callable is not injected."""
    from vsa_agent.registry import ToolRegistry

    fn = ToolRegistry.get(tool_name)
    if fn is None:
        raise RuntimeError(f"Search tool '{tool_name}' is not registered.")

    async def _callable():
        return await fn(**kwargs)

    return _callable


async def _run_embed_search(query: str, top_k: int, embed_store=None) -> SearchOutput:
    if embed_store is not None:
        return await embed_store.search(query=query, top_k=top_k)

    from vsa_agent.registry import ToolRegistry

    fn = ToolRegistry.get("embed_search")
    if fn is not None:
        return await fn(query=query, top_k=top_k)

    from vsa_agent.tools.vector_store import get_default_embed_store

    return await get_default_embed_store().search(query=query, top_k=top_k)


async def _run_attribute_search(attributes: list[str], top_k: int, attr_store=None) -> SearchOutput:
    if attr_store is not None:
        return await attr_store.search_by_attributes(attributes=attributes, top_k=top_k)

    from vsa_agent.registry import ToolRegistry

    fn = ToolRegistry.get("attribute_search")
    if fn is not None:
        return await fn(attributes=attributes, top_k=top_k)

    from vsa_agent.tools.vector_store import get_default_attr_store

    return await get_default_attr_store().search_by_attributes(attributes=attributes, top_k=top_k)


# ===== Registered Tool =====


@register_tool(
    "search",
    description="Core video search with three-path routing: "
    "embed-only, attribute-only, or fusion (embed + attribute rerank). "
    "Accepts optional decomposed query parameters for path selection.",
)
async def search_tool(
    query: str,
    embed_store=None,
    attr_store=None,
    decomposed_attributes: list[str] | None = None,
    decomposed_has_action: bool | None = None,
    top_k: int = 10,
) -> SearchOutput:
    """Execute video search with automatic path selection."""
    if not query or not query.strip():
        raise ValueError("Search query must be a non-empty string")

    attributes = decomposed_attributes or []
    has_action = decomposed_has_action

    if has_action is False and attributes:
        logger.info("Path 1: attribute-only search")
        try:
            return await _run_attribute_search(attributes, top_k, attr_store)
        except Exception as e:
            logger.error("Attribute-only search failed: %s", e)
            return SearchOutput(data=[])

    if not attributes:
        logger.info("Path 2: embed-only search")
        try:
            return await _run_embed_search(query, top_k, embed_store)
        except Exception as e:
            logger.error("Embed-only search failed: %s", e)
            return SearchOutput(data=[])

    logger.info("Path 3: fusion search (embed + attribute rerank)")
    embed_results: list[SearchResult] = []
    attr_results: list[SearchResult] = []

    try:
        embed_output = await _run_embed_search(query, top_k, embed_store)
        embed_results = normalize_search_results(embed_output)
    except Exception as e:
        logger.error("Embed search in fusion failed: %s", e)

    try:
        attr_output = await _run_attribute_search(attributes, top_k, attr_store)
        attr_results = normalize_search_results(attr_output)
    except Exception as e:
        logger.error("Attribute search in fusion failed: %s", e)

    combined = rank_unique_results([*embed_results, *attr_results])
    return SearchOutput(data=trim_search_results(combined, top_k))


# ===== Non-Streaming Wrapper (Phase B) =====


async def execute_core_search_wrapper(
    search_input,
    embed_search,
    agent_llm=None,
    config=None,
    builder=None,
    attribute_search_fn=None,
    critic_agent=None,
):
    """Non-streaming wrapper: collects generator output, returns final SearchOutput."""
    async for update in execute_core_search(
        search_input=search_input,
        embed_search=embed_search,
        agent_llm=agent_llm,
        config=config,
        attribute_search_fn=attribute_search_fn,
    ):
        if isinstance(update, SearchOutput):
            return update
    return SearchOutput(data=[])
