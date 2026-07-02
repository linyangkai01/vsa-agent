from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable
from typing import Callable

from vsa_agent.archive.index import read_archive_index
from vsa_agent.archive.models import ArchiveRecord
from vsa_agent.tools.search import SearchOutput


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_\-\u4e00-\u9fff]+", text.lower())
        if token
    }


def _score(query: str, record: ArchiveRecord) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0

    haystack = f"{record.description}\n{record.search_text}".lower()
    record_tokens = _tokens(haystack)
    overlap = query_tokens & record_tokens
    if not overlap:
        return 0.0

    token_score = len(overlap) / len(query_tokens)
    phrase_boost = 0.15 if query.lower().strip() in haystack else 0.0
    return min(1.0, token_score + phrase_boost)


class LocalArchiveSearchStore:
    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path)

    async def search(self, query: str, top_k: int = 10) -> SearchOutput:
        scored = [
            (score, record)
            for record in read_archive_index(self.index_path)
            if (score := _score(query, record)) > 0
        ]
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
        return SearchOutput(
            data=[record.to_search_result(similarity=score) for score, record in ranked]
        )

    def as_embed_search(self, query: str, top_k: int = 10) -> Callable[[], Awaitable[SearchOutput]]:
        async def _search() -> SearchOutput:
            return await self.search(query=query, top_k=top_k)

        return _search
