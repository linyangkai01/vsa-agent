#!/usr/bin/env python3
"""Deterministic OpenAI-compatible provider for recorded-video Playwright tests."""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DESCRIPTION = "A forklift operates near a worker in an industrial area."
TAGS = ["forklift", "worker", "industrial-safety"]
CHAT_FINAL_ANSWER = "The selected segment shows a forklift operating near a worker in an industrial area."
EMBEDDING_DIMS = 1024
EMBEDDING = [0.03125] * EMBEDDING_DIMS


def _message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def _latest_user_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return _message_text(message)
    return ""


def _has_tool_result(payload: dict[str, Any]) -> bool:
    messages = payload.get("messages")
    return isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "tool" for message in messages
    )


def _offers_video_understanding(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return False
    return any(
        isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") == "video_understanding"
        for tool in tools
    )


def _context_line(text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _video_understanding_arguments(payload: dict[str, Any]) -> dict[str, str] | None:
    user_text = _latest_user_text(payload)
    context_marker = "\n\nSelected recorded video context (server validated):"
    if context_marker not in user_text:
        return None
    video_path = _context_line(user_text, "video_path")
    if not video_path:
        return None
    question = user_text.split(context_marker, 1)[0].strip()
    arguments = {
        "video_path": video_path,
        "query": question,
        "source_type": "video_file",
    }
    start_timestamp = _context_line(user_text, "start_timestamp")
    end_timestamp = _context_line(user_text, "end_timestamp")
    if start_timestamp:
        arguments["start_timestamp"] = start_timestamp
    if end_timestamp:
        arguments["end_timestamp"] = end_timestamp
    return arguments


def _chat_completion(model: str, message: dict[str, Any], finish_reason: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-playwright",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class ProviderControlConflictError(RuntimeError):
    """The requested provider control transition conflicts with active state."""


class ProviderState:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._release_event = threading.Event()
        self._block_next_vision = False
        self._blocked_vision_requests = 0

    def arm_next_vision(self) -> dict[str, int | bool]:
        with self._condition:
            if self._block_next_vision or self._blocked_vision_requests > 0:
                raise ProviderControlConflictError("vision block is already armed or active")
            self._release_event = threading.Event()
            self._block_next_vision = True
            return self._snapshot_unlocked()

    def wait_if_armed(self) -> None:
        with self._condition:
            if not self._block_next_vision:
                return
            release_event = self._release_event
            self._block_next_vision = False
            self._blocked_vision_requests += 1
            self._condition.notify_all()
        try:
            release_event.wait()
        finally:
            with self._condition:
                self._blocked_vision_requests -= 1
                self._condition.notify_all()

    def release(self) -> dict[str, int | bool]:
        with self._condition:
            self._block_next_vision = False
            release_event = self._release_event
            snapshot = self._snapshot_unlocked()
            release_event.set()
            self._condition.notify_all()
            return snapshot

    def snapshot(self) -> dict[str, int | bool]:
        with self._condition:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict[str, int | bool]:
        return {
            "block_next_vision": self._block_next_vision,
            "blocked_vision_requests": self._blocked_vision_requests,
        }


class ProviderServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, ProviderHandler)
        self.state = ProviderState()


class ProviderHandler(BaseHTTPRequestHandler):
    server: ProviderServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[e2e-provider] {self.address_string()} {format % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol method
        if self.path == "/health":
            self._json({"status": "ok"})
            return
        if self.path == "/control/state":
            self._json(self.server.state.snapshot())
            return
        if self.path == "/v1/models":
            self._json(
                {
                    "object": "list",
                    "data": [
                        {"id": "playwright-vision", "object": "model", "owned_by": "playwright"},
                        {"id": "playwright-embedding", "object": "model", "owned_by": "playwright"},
                    ],
                }
            )
            return
        self._json({"error": {"message": "not found", "type": "invalid_request_error"}}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol method
        payload = self._read_json()
        if payload is None:
            return
        if self.path == "/control/block-next-vision":
            try:
                state = self.server.state.arm_next_vision()
            except ProviderControlConflictError as error:
                self._json(
                    {"error": {"message": str(error), "type": "conflict_error"}},
                    HTTPStatus.CONFLICT,
                )
                return
            self._json(state)
            return
        if self.path == "/control/release":
            self._json(self.server.state.release())
            return
        if self.path == "/v1/chat/completions":
            model = str(payload.get("model") or "playwright-vision")
            if model == "playwright-vision":
                self.server.state.wait_if_armed()
                content = json.dumps({"description": DESCRIPTION, "tags": TAGS})
                self._json(
                    _chat_completion(
                        model,
                        {"role": "assistant", "content": content, "refusal": None},
                        "stop",
                    )
                )
                return

            if model == "playwright-chat" and _has_tool_result(payload):
                self._json(
                    _chat_completion(
                        model,
                        {"role": "assistant", "content": CHAT_FINAL_ANSWER, "refusal": None},
                        "stop",
                    )
                )
                return

            arguments = _video_understanding_arguments(payload)
            if model == "playwright-chat" and _offers_video_understanding(payload) and arguments:
                self._json(
                    _chat_completion(
                        model,
                        {
                            "role": "assistant",
                            "content": None,
                            "refusal": None,
                            "tool_calls": [
                                {
                                    "id": "call-playwright-video-understanding",
                                    "type": "function",
                                    "function": {
                                        "name": "video_understanding",
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        },
                        "tool_calls",
                    )
                )
                return

            self._json(
                _chat_completion(
                    model,
                    {
                        "role": "assistant",
                        "content": "No selected recorded-video context was provided.",
                        "refusal": None,
                    },
                    "stop",
                )
            )
            return
        if self.path == "/v1/embeddings":
            model = str(payload.get("model") or "playwright-embedding")
            self._json(
                {
                    "object": "list",
                    "data": [{"object": "embedding", "index": 0, "embedding": EMBEDDING}],
                    "model": model,
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            )
            return
        self._json({"error": {"message": "not found", "type": "invalid_request_error"}}, HTTPStatus.NOT_FOUND)

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (json.JSONDecodeError, TypeError, ValueError):
            self._json(
                {"error": {"message": "invalid JSON object", "type": "invalid_request_error"}},
                HTTPStatus.BAD_REQUEST,
            )
            return None

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8399)
    options = parser.parse_args()
    server = ProviderServer((options.host, options.port))

    def stop_server(*_: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)
    try:
        server.serve_forever()
    finally:
        server.state.release()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
