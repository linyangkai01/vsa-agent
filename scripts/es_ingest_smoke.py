from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any
from urllib.request import Request
from urllib.request import urlopen

from elasticsearch import AsyncElasticsearch


def mock_query_vector(query: str) -> list[float]:
    seed = sum(ord(char) for char in query) % 1000
    return [seed * 0.001, seed * 0.002, seed * 0.003, (seed % 100) * 0.01]


def sample_payload(video_id: str, query: str = "forklift near worker") -> dict[str, Any]:
    return {
        "video_id": video_id,
        "metadata": {
            "video_name": "runtime-validation.mp4",
            "description": "forklift passes near worker in loading zone",
            "sensor_id": "camera-runtime-1",
            "start_time": "2026-07-04T08:00:00Z",
            "end_time": "2026-07-04T08:00:05Z",
            "screenshot_url": "http://example.invalid/frames/runtime-validation.jpg",
            "vector": mock_query_vector(query),
            "site": "runtime-yard",
        },
    }


def validate_ingest_response(payload: dict[str, Any], expected_video_id: str) -> str:
    if payload.get("status") != "ingested" or payload.get("indexed") is not True:
        raise RuntimeError(f"Expected ingested/indexed response, got: {payload}")
    if payload.get("video_id") != expected_video_id:
        raise RuntimeError(f"Expected video_id {expected_video_id!r}, got {payload.get('video_id')!r}")
    result_id = payload.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        raise RuntimeError(f"Expected non-empty result_id, got: {result_id!r}")
    return result_id


def validate_indexed_document(document: dict[str, Any], expected_video_id: str) -> None:
    expected = sample_payload(expected_video_id)["metadata"]
    checks = {
        "video_id": expected_video_id,
        "video_name": expected["video_name"],
        "description": expected["description"],
        "sensor_id": expected["sensor_id"],
        "start_time": expected["start_time"],
        "end_time": expected["end_time"],
        "screenshot_url": expected["screenshot_url"],
        "vector": expected["vector"],
    }
    for key, value in checks.items():
        if document.get(key) != value:
            raise RuntimeError(f"Indexed document field {key!r} mismatch: expected {value!r}, got {document.get(key)!r}")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("site") != "runtime-yard":
        raise RuntimeError(f"Indexed document metadata missing expected site: {metadata!r}")


def post_ingest(api_url: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    request = Request(
        f"{api_url.rstrip('/')}/api/search/ingest",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_sec) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(response_payload, dict):
        raise RuntimeError(f"Expected JSON object from ingest API, got: {response_payload!r}")
    return response_payload


def post_original_ui_search(api_url: str, query: str, top_k: int, timeout_sec: float) -> dict[str, Any]:
    request = Request(
        f"{api_url.rstrip('/')}/api/v1/search",
        data=json.dumps({"query": query, "top_k": top_k, "source_type": "video_file", "agent_mode": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"Expected {{'data': [...]}} from /api/v1/search, got: {payload!r}")
    return payload


async def find_indexed_document(
    es_endpoint: str,
    index: str,
    video_id: str,
    timeout_sec: float,
    verify_certs: bool,
) -> dict[str, Any]:
    es = AsyncElasticsearch(es_endpoint, request_timeout=timeout_sec, verify_certs=verify_certs)
    try:
        await es.indices.refresh(index=index)
        for body in (
            {"query": {"term": {"video_id.keyword": video_id}}, "size": 1},
            {"query": {"match": {"video_id": video_id}}, "size": 1},
        ):
            result = await es.search(index=index, body=body)
            hits = result.get("hits", {}).get("hits", [])
            if hits:
                source = hits[0].get("_source", {})
                if not isinstance(source, dict):
                    raise RuntimeError(f"Expected indexed document source to be an object, got: {source!r}")
                return source
    finally:
        await es.close()

    raise RuntimeError(f"Indexed document not found for video_id={video_id!r} in index={index!r}")


async def search_indexed_document(
    es_endpoint: str,
    index: str,
    video_id: str,
    query: str,
    timeout_sec: float,
    verify_certs: bool,
) -> dict[str, Any]:
    es = AsyncElasticsearch(es_endpoint, request_timeout=timeout_sec, verify_certs=verify_certs)
    try:
        body = {
            "query": {
                "bool": {
                    "must": [{"multi_match": {
                        "query": query,
                        "fields": ["description", "video_name", "sensor_id", "metadata.description", "metadata.site"],
                    }}],
                    "filter": [{"term": {"video_id.keyword": video_id}}],
                }
            },
            "size": 1,
        }
        result = await es.search(index=index, body=body)
        hits = result.get("hits", {}).get("hits", [])
        if hits:
            source = hits[0].get("_source", {})
            if not isinstance(source, dict):
                raise RuntimeError(f"Expected search hit source to be an object, got: {source!r}")
            return source
    finally:
        await es.close()

    raise RuntimeError(f"Search validation found no hits for query={query!r} in index={index!r}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate /api/search/ingest against a real Elasticsearch index.")
    parser.add_argument("--api-url", default=os.environ.get("VSA_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--es-endpoint", default=os.environ.get("VSA_ES_ENDPOINT"))
    parser.add_argument("--index", default=os.environ.get("VSA_ES_INDEX", "vsa-video-embeddings"))
    parser.add_argument("--video-id", default=f"runtime-video-{int(time.time())}")
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--search-query", default="forklift near worker")
    parser.add_argument("--insecure", action="store_true", help="Disable Elasticsearch TLS certificate verification.")
    args = parser.parse_args(argv)
    if not args.es_endpoint:
        parser.error("--es-endpoint is required when VSA_ES_ENDPOINT is not set")
    return args


async def _run(args: argparse.Namespace) -> None:
    payload = sample_payload(args.video_id, args.search_query)
    ingest_response = post_ingest(args.api_url, payload, timeout_sec=args.timeout_sec)
    validate_ingest_response(ingest_response, expected_video_id=args.video_id)
    document = await find_indexed_document(
        args.es_endpoint,
        index=args.index,
        video_id=args.video_id,
        timeout_sec=args.timeout_sec,
        verify_certs=not args.insecure,
    )
    validate_indexed_document(document, expected_video_id=args.video_id)
    search_hit = await search_indexed_document(
        args.es_endpoint,
        index=args.index,
        video_id=args.video_id,
        query="forklift worker",
        timeout_sec=args.timeout_sec,
        verify_certs=not args.insecure,
    )
    if search_hit.get("video_id") != args.video_id:
        raise RuntimeError(
            f"Search hit video_id mismatch: expected {args.video_id!r}, got {search_hit.get('video_id')!r}"
        )
    ui_search = post_original_ui_search(args.api_url, args.search_query, 1, args.timeout_sec)
    expected_name = payload["metadata"]["video_name"]
    if expected_name not in {item.get("video_name") for item in ui_search["data"] if isinstance(item, dict)}:
        raise RuntimeError(f"Original UI search did not return video_name={expected_name!r}: {ui_search!r}")
    print("PASS: Elasticsearch ingest and search smoke validation")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
