"""Original VSS Search API adapter."""

import logging

from fastapi import APIRouter, HTTPException

from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
from vsa_agent.tools.embed_search import SearchDependencyError
from vsa_agent.tools.search import SearchInput, SearchOutput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchOutput)
async def original_ui_search(request: SearchInput) -> SearchOutput:
    """Serve the response shape consumed by the original VSS Search UI."""
    top_k = request.top_k or 10
    logger.info(
        "original_ui.search.request query=%r top_k=%d agent_mode=%s",
        request.query,
        top_k,
        request.agent_mode,
    )
    try:
        return await execute_search(
            SearchAgentInput(
                query=request.query,
                agent_mode=request.agent_mode,
                max_results=top_k,
                top_k=top_k,
                video_sources=request.video_sources or [],
                start_time=request.timestamp_start,
                end_time=request.timestamp_end,
                min_cosine_similarity=request.min_cosine_similarity,
                source_type=request.source_type,
                use_critic=request.use_critic,
            )
        )
    except SearchDependencyError:
        raise HTTPException(status_code=503, detail="production search dependency is unavailable") from None
