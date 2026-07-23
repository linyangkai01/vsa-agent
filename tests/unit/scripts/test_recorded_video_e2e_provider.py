from __future__ import annotations

import json
import runpy
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
PROVIDER_SCRIPT = (
    REPO_ROOT / "frontend" / "original-ui" / "apps" / "nv-metropolis-bp-vss-ui" / "e2e" / "fake-openai-provider.py"
)
PLAYWRIGHT_CONFIG = REPO_ROOT / "frontend" / "original-ui" / "apps" / "nv-metropolis-bp-vss-ui" / "playwright.config.ts"
E2E_RUNTIME_CONFIG = PROVIDER_SCRIPT.with_name("config.e2e.yaml")
PROVIDER_STATE_CLASS = runpy.run_path(str(PROVIDER_SCRIPT))["ProviderState"]


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        assert response.status == 200
        return json.load(response)


@contextmanager
def _provider() -> Iterator[str]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, str(PROVIDER_SCRIPT), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                _request_json(f"{base_url}/health")
                break
            except (OSError, urllib.error.URLError):
                if process.poll() is not None or time.monotonic() >= deadline:
                    stdout, stderr = process.communicate(timeout=1)
                    raise AssertionError(
                        f"fake provider failed to start (exit={process.returncode})\n{stdout}\n{stderr}"
                    )
                time.sleep(0.02)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _vision_request(base_url: str) -> dict[str, object]:
    return _request_json(
        f"{base_url}/v1/chat/completions",
        {
            "model": "playwright-vision",
            "messages": [{"role": "user", "content": "describe frames"}],
            "response_format": {"type": "json_object"},
        },
    )


def test_fake_provider_returns_fixed_openai_compatible_results() -> None:
    with _provider() as base_url:
        vision = _vision_request(base_url)
        content = json.loads(vision["choices"][0]["message"]["content"])  # type: ignore[index]
        embedding = _request_json(
            f"{base_url}/v1/embeddings",
            {"model": "playwright-embedding", "input": "forklift"},
        )
        vector = embedding["data"][0]["embedding"]  # type: ignore[index]

    assert content == {
        "description": "A forklift operates near a worker in an industrial area.",
        "tags": ["forklift", "worker", "industrial-safety"],
    }
    assert isinstance(vector, list)
    assert len(vector) == 1024
    assert all(type(value) is float for value in vector)


def test_fake_provider_blocks_exactly_the_next_vision_request() -> None:
    with _provider() as base_url, ThreadPoolExecutor(max_workers=1) as executor:
        armed = _request_json(f"{base_url}/control/block-next-vision", {})
        assert armed == {"block_next_vision": True, "blocked_vision_requests": 0}

        blocked_request = executor.submit(_vision_request, base_url)
        deadline = time.monotonic() + 3
        while True:
            state = _request_json(f"{base_url}/control/state")
            if state["blocked_vision_requests"] == 1:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert not blocked_request.done()

        released = _request_json(f"{base_url}/control/release", {})
        assert released == {"block_next_vision": False, "blocked_vision_requests": 1}
        blocked_request.result(timeout=3)

        state = _request_json(f"{base_url}/control/state")
        assert state == {"block_next_vision": False, "blocked_vision_requests": 0}
        _vision_request(base_url)


def test_fake_provider_does_not_consume_vision_block_for_text_chat() -> None:
    with _provider() as base_url, ThreadPoolExecutor(max_workers=1) as executor:
        _request_json(f"{base_url}/control/block-next-vision", {})
        text_request = executor.submit(
            _request_json,
            f"{base_url}/v1/chat/completions",
            {
                "model": "playwright-chat",
                "messages": [{"role": "user", "content": "summarize text"}],
            },
        )
        try:
            text_request.result(timeout=0.5)
        finally:
            _request_json(f"{base_url}/control/release", {})


def test_provider_release_wakes_captured_event_before_rearm() -> None:
    state = PROVIDER_STATE_CLASS()
    state.arm_next_vision()
    first_release = state._release_event
    wait_entered = threading.Event()
    continue_wait = threading.Event()
    original_wait = first_release.wait

    def delayed_wait() -> bool:
        wait_entered.set()
        assert continue_wait.wait(timeout=1)
        return original_wait()

    first_release.wait = delayed_wait
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_request = executor.submit(state.wait_if_armed)
        assert wait_entered.wait(timeout=1)
        state.release()
        with pytest.raises(RuntimeError, match="vision block is already armed or active"):
            state.arm_next_vision()
        continue_wait.set()
        try:
            first_request.result(timeout=0.5)
        except FutureTimeoutError:
            state.release()
            first_request.result(timeout=1)
            raise

        state.arm_next_vision()
        assert state.snapshot() == {
            "block_next_vision": True,
            "blocked_vision_requests": 0,
        }
        second_request = executor.submit(state.wait_if_armed)
        try:
            deadline = time.monotonic() + 1
            while state.snapshot()["blocked_vision_requests"] != 1:
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert not second_request.done()
        finally:
            state.release()
            second_request.result(timeout=1)


def test_provider_rejects_rearm_before_the_pending_block_is_consumed() -> None:
    state = PROVIDER_STATE_CLASS()
    state.arm_next_vision()
    first_release = state._release_event
    try:
        with pytest.raises(RuntimeError, match="vision block is already armed or active"):
            state.arm_next_vision()
        assert state._release_event is first_release
        assert state.snapshot() == {
            "block_next_vision": True,
            "blocked_vision_requests": 0,
        }
    finally:
        state.release()


def test_provider_rejects_rearm_while_a_vision_request_is_blocked() -> None:
    state = PROVIDER_STATE_CLASS()
    state.arm_next_vision()
    first_release = state._release_event
    with ThreadPoolExecutor(max_workers=1) as executor:
        blocked_request = executor.submit(state.wait_if_armed)
        deadline = time.monotonic() + 1
        while state.snapshot()["blocked_vision_requests"] != 1:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        try:
            with pytest.raises(RuntimeError, match="vision block is already armed or active"):
                state.arm_next_vision()
            assert state._release_event is first_release
            state.release()
            blocked_request.result(timeout=1)
        finally:
            first_release.set()
            state.release()


def test_provider_control_returns_conflict_for_duplicate_arm() -> None:
    with _provider() as base_url:
        _request_json(f"{base_url}/control/block-next-vision", {})
        try:
            with pytest.raises(urllib.error.HTTPError) as captured:
                _request_json(f"{base_url}/control/block-next-vision", {})
            assert captured.value.status == 409
            assert json.load(captured.value) == {
                "error": {
                    "message": "vision block is already armed or active",
                    "type": "conflict_error",
                }
            }
        finally:
            _request_json(f"{base_url}/control/release", {})


def test_provider_snapshot_reads_state_under_its_condition() -> None:
    state = PROVIDER_STATE_CLASS()

    class TrackingCondition:
        def __init__(self) -> None:
            self.entries = 0

        def __enter__(self) -> TrackingCondition:
            self.entries += 1
            return self

        def __exit__(self, *_: object) -> None:
            return None

    condition = TrackingCondition()
    state._condition = condition

    state.snapshot()

    assert condition.entries == 1


def test_playwright_runtime_uses_the_controlled_provider_profile() -> None:
    playwright = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    runtime = E2E_RUNTIME_CONFIG.read_text(encoding="utf-8")

    assert "fake-openai-provider.py" in playwright
    assert "VSA_LOCAL_CONFIG" in playwright
    assert "PLAYWRIGHT_PROVIDER_API_KEY" in playwright
    assert "PLAYWRIGHT_CONDA_ENV" in playwright
    assert "conda run --no-capture-output -n ${condaEnv} python" in playwright
    assert "--conda-env ${condaEnv}" in playwright
    assert "active_profile: playwright_e2e" in runtime
    assert "base_url: http://127.0.0.1:8399/v1" in runtime
    assert "allow_mock_fallback: false" in runtime
    assert "force_mock_embedding: false" in runtime
