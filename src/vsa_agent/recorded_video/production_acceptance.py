"""Production recorded-video acceptance orchestration primitives."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    path: Path
    query: str
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_cases(video_paths: Sequence[Path], queries: Sequence[str]):
    if len(video_paths) != 3:
        raise ValueError("production acceptance requires three distinct video files")

    try:
        resolved = tuple(Path(path).resolve(strict=True) for path in video_paths)
        if not all(path.is_file() for path in resolved):
            raise OSError("not a regular file")
        digests = tuple(_sha256(path) for path in resolved)
    except OSError:
        raise ValueError("production acceptance requires regular readable video files") from None
    if len(set(resolved)) != 3 or len(set(digests)) != 3:
        raise ValueError("production acceptance requires three distinct video files")

    if len(queries) not in (1, 3) or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("production acceptance requires one or three non-empty queries")
    normalized_queries = tuple(query.strip() for query in queries)
    mapped_queries = normalized_queries * 3 if len(normalized_queries) == 1 else normalized_queries

    return tuple(
        AcceptanceCase(path=path, query=query, sha256=digest)
        for path, query, digest in zip(resolved, mapped_queries, digests, strict=True)
    )
