"""Original VSS Search API adapter."""

import logging

from fastapi import APIRouter

from vsa_agent.agents.search_agent import SearchAgentInput, execute_search
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
    return await execute_search(
        SearchAgentInput(
            query=request.query,
            agent_mode=request.agent_mode,
            max_results=top_k,
            top_k=top_k,
            start_time=request.timestamp_start,
            end_time=request.timestamp_end,
            source_type=request.source_type,
            use_critic=request.use_critic,
        )
    )
