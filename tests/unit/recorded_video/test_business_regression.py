from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx
import yaml

from vsa_agent.recorded_video.business_regression import (
    BusinessRegressionOptions,
    run_business_regression,
)

from .test_business_manifest import _manifest_payload


def _dataset(tmp_path: Path) -> tuple[Path, Path]:
    payload = _manifest_payload()
    root = tmp_path / "dataset"
    clips = root / "clips"
    sources = root / "sources"
    clips.mkdir(parents=True)
    sources.mkdir()
    source_bytes = b"source-video"
    source = payload["sources"][0]
    source["size_bytes"] = len(source_bytes)
    source["sha256"] = hashlib.sha256(source_bytes).hexdigest()
    (sources / source["filename"]).write_bytes(source_bytes)
    for index, case in enumerate(payload["cases"]):
        content = f"clip-{index}".encode()
        case["clip"]["sha256"] = hashlib.sha256(content).hexdigest()
        (clips / case["clip"]["filename"]).write_bytes(content)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return manifest, root


class _BusinessApi:
    def __init__(
        self,
        manifest: Path,
        root: Path,
        *,
        transient_chat: bool = False,
        fail_chat: bool = False,
        intermediate_only_concepts: bool = False,
        fail_upload: bool = False,
        job_status: str = "completed",
        fail_cleanup: bool = False,
        provider_ready: bool = True,
        incomplete_chat_trace: bool = False,
        cached_chat_tool_call: bool = False,
        duplicate_chat_tool_execution: bool = False,
    ) -> None:
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        self.file_sizes = {
            case["clip"]["filename"]: (root / "clips" / case["clip"]["filename"]).stat().st_size
            for case in payload["cases"]
        }
        self.asset_by_filename: dict[str, str] = {}
        self.job_by_asset: dict[str, str] = {}
        self.asset_status: dict[str, str] = {}
        self.deleted: set[str] = set()
        self.chat_calls = 0
        self.transient_chat = transient_chat
        self.fail_chat = fail_chat
        self.intermediate_only_concepts = intermediate_only_concepts
        self.fail_upload = fail_upload
        self.job_status = job_status
        self.fail_cleanup = fail_cleanup
        self.provider_ready = provider_ready
        self.incomplete_chat_trace = incomplete_chat_trace
        self.cached_chat_tool_call = cached_chat_tool_call
        self.duplicate_chat_tool_execution = duplicate_chat_tool_execution
        self.chat_traces: dict[str, dict[str, object]] = {}

    def _json(self, request: httpx.Request) -> dict[str, object]:
        return json.loads(request.content.decode())

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/v1/runtime/evidence":
            role = {
                "backend": "dashscope",
                "provider": "dashscope",
                "model": "production-model",
                "api_key_required": True,
                "api_key_configured": True,
                "is_mock": not self.provider_ready,
            }
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "active_profile": "production",
                    "recorded_video_enabled": True,
                    "roles": {"llm": role, "vlm": role, "embedding": role},
                    "search": {
                        "allow_mock_fallback": False,
                        "force_mock_embedding": False,
                    },
                    "real_provider_ready": self.provider_ready,
                    "config_fingerprint": "a" * 64,
                },
            )
        if request.method == "POST" and path == "/api/v1/videos":
            filename = str(self._json(request)["filename"])
            asset_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            self.asset_by_filename[filename] = asset_id
            self.asset_status[asset_id] = "uploading"
            return httpx.Response(
                200,
                json={
                    "asset_id": asset_id,
                    "upload_session_id": session_id,
                    "url": f"/api/v1/vst/v1/storage/file?upload_session_id={session_id}",
                },
            )
        if request.method == "POST" and path == "/api/v1/vst/v1/storage/file":
            filename = request.headers["nvstreamer-file-name"]
            asset_id = self.asset_by_filename[filename]
            if self.fail_upload:
                return httpx.Response(500, text="chunk upload failed")
            return httpx.Response(
                200,
                json={
                    "sensorId": asset_id,
                    "streamId": asset_id,
                    "bytes": self.file_sizes[filename],
                    "chunkCount": 1,
                },
            )
        complete = re_fullmatch(r"/api/v1/videos/([^/]+)/complete", path)
        if request.method == "POST" and complete:
            asset_id = complete.group(1)
            if self.asset_status.get(asset_id) != "uploading":
                return httpx.Response(409, text="asset is not uploadable")
            job_id = str(uuid.uuid4())
            self.job_by_asset[asset_id] = job_id
            self.asset_status[asset_id] = "ready"
            return httpx.Response(
                202,
                json={
                    "asset_id": asset_id,
                    "job_id": job_id,
                    "status": "queued",
                    "status_url": f"/api/v1/jobs/{job_id}",
                },
            )
        job = re_fullmatch(r"/api/v1/jobs/([^/]+)", path)
        if request.method == "GET" and job:
            job_id = job.group(1)
            asset_id = next(asset for asset, candidate in self.job_by_asset.items() if candidate == job_id)
            return httpx.Response(
                200,
                json={
                    "asset_id": asset_id,
                    "job_id": job_id,
                    "status": self.job_status,
                    "stage": "publish" if self.job_status == "completed" else "segmenting",
                    "attempt": 1,
                },
            )
        if request.method == "POST" and path == "/api/v1/search":
            body = self._json(request)
            filename = str(body["video_sources"][0])
            asset_id = self.asset_by_filename[filename]
            now = datetime.now(UTC)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "asset_id": asset_id,
                            "segment_id": f"segment-{asset_id}",
                            "job_id": self.job_by_asset[asset_id],
                            "video_name": filename,
                            "description": "industrial safety scene",
                            "start_time": now.isoformat().replace("+00:00", "Z"),
                            "end_time": (now + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
                            "sensor_id": asset_id,
                            "screenshot_url": f"/api/v1/videos/{asset_id}/segments/segment/thumbnail",
                            "similarity": 0.95,
                            "object_ids": [],
                        }
                    ]
                },
            )
        if request.method == "GET" and path.endswith("/thumbnail"):
            return httpx.Response(200, content=b"thumbnail")
        media = re_fullmatch(r"/api/v1/vst/v1/storage/file/([^/]+)", path)
        if request.method == "GET" and media:
            asset_id = media.group(1)
            if asset_id in self.deleted:
                return httpx.Response(404)
            return httpx.Response(
                206,
                content=b"x",
                headers={"Accept-Ranges": "bytes", "Content-Range": "bytes 0-0/9"},
            )
        if request.method == "POST" and path == "/api/chat":
            self.chat_calls += 1
            if self.fail_chat:
                return httpx.Response(500, text="provider unavailable")
            if self.transient_chat and self.chat_calls == 1:
                return httpx.Response(503, text="temporary provider outage")
            body = self._json(request)
            content = str(body["messages"][0]["content"])
            context_json, _ = content.removeprefix("[Context: ").split("]\n", 1)
            context = json.loads(context_json)[0]
            trace_id = str(uuid.uuid4())
            event_types = [
                "original_ui.chat.request",
                "top_agent.tool.call",
                "video_understanding.result",
                "top_agent.tool.result",
                "top_agent.final",
            ]
            if self.incomplete_chat_trace:
                event_types.remove("video_understanding.result")
            self.chat_traces[trace_id] = {
                "schema_version": 1,
                "trace_id": trace_id,
                "conversation_id": request.headers["Conversation-Id"],
                "user_message_id": request.headers["User-Message-ID"],
                "selected_asset_id": context["assetId"],
                "selected_segment_id": context["segmentId"],
                "event_types": event_types,
                "missing_event_types": (["video_understanding.result"] if self.incomplete_chat_trace else []),
                "video_tool_call_count": 1,
                "video_tool_execution_count": 1,
                "video_tool_cached_result_count": 0,
                "video_tool_calls_consistent": True,
                "final_count": 1,
                "final_nonempty": True,
                "error_event_types": [],
                "provider_request_ids": [f"request-{trace_id}"],
            }
            if self.cached_chat_tool_call:
                self.chat_traces[trace_id]["video_tool_call_count"] = 2
                self.chat_traces[trace_id]["video_tool_cached_result_count"] = 1
            if self.duplicate_chat_tool_execution:
                self.chat_traces[trace_id]["video_tool_call_count"] = 2
                self.chat_traces[trace_id]["video_tool_execution_count"] = 2
            headers = {"X-VSA-Trace-ID": trace_id}
            if self.intermediate_only_concepts:
                return httpx.Response(
                    200,
                    text=(
                        '<intermediatestep>{"content":{"payload":"forklift worker near PPE working"}}'
                        "</intermediatestep>Unclear scene."
                    ),
                    headers=headers,
                )
            answer = "A person and a forklift are visible in this industrial scene."
            return httpx.Response(200, text=answer, headers=headers)
        trace_evidence = re_fullmatch(r"/api/v1/runtime/chat-traces/([^/]+)/evidence", path)
        if request.method == "GET" and trace_evidence:
            trace = self.chat_traces.get(trace_evidence.group(1))
            return httpx.Response(200, json=trace) if trace is not None else httpx.Response(404)
        delete = re_fullmatch(r"/api/v1/videos/([^/]+)", path)
        if request.method == "DELETE" and delete:
            if self.fail_cleanup:
                return httpx.Response(500, text="cleanup unavailable")
            asset_id = delete.group(1)
            if asset_id not in self.asset_status:
                return httpx.Response(404)
            self.asset_status[asset_id] = "deleted"
            self.deleted.add(asset_id)
            return httpx.Response(204)
        return httpx.Response(500, text=f"unexpected request: {request.method} {path}")


def re_fullmatch(pattern: str, value: str):
    import re

    return re.fullmatch(pattern, value)


def _options(tmp_path: Path, manifest: Path, root: Path, profile: str) -> BusinessRegressionOptions:
    return BusinessRegressionOptions(
        manifest=manifest,
        data_root=root,
        profile=profile,
        api_url="http://api.test",
        ui_url="http://ui.test",
        output_root=tmp_path / "reports",
        timeout=10.0,
        poll_interval=0.001,
        request_attempts=2,
        run_id=f"run-{profile}",
    )


def test_quick_regression_runs_six_cases_and_writes_json_junit_and_attempts(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root)
    client = httpx.Client(transport=httpx.MockTransport(api))

    exit_code = run_business_regression(_options(tmp_path, manifest, root, "quick"), client=client)

    assert exit_code == 0
    run_dir = tmp_path / "reports" / "run-quick"
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert len(report["cases"]) == 6
    assert len(report["assets"]) == 6
    assert len(report["cleanup"]) == 6
    assert len(list((run_dir / "cases").glob("*/*.json"))) == 6
    suite = ElementTree.parse(run_dir / "junit.xml").getroot()
    assert suite.attrib == {
        "name": "business-video-regression",
        "tests": "6",
        "failures": "0",
        "errors": "0",
        "skipped": "0",
    }


def test_release_chat_failure_is_not_retried_transparently(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, transient_chat=True)
    client = httpx.Client(transport=httpx.MockTransport(api))

    exit_code = run_business_regression(_options(tmp_path, manifest, root, "release"), client=client)

    assert exit_code == 3
    report = json.loads((tmp_path / "reports" / "run-release" / "report.json").read_text(encoding="utf-8"))
    assert api.chat_calls == 1
    assert report["failure_category"] == "pipeline_error"
    assert report["cases"][0]["failure_category"] == "pipeline_error"


def test_dataset_failure_has_exit_code_two_and_a_failing_junit_case(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    next((root / "clips").iterdir()).unlink()
    options = _options(tmp_path, manifest, root, "quick")

    exit_code = run_business_regression(options, client=httpx.Client(transport=httpx.MockTransport(lambda _: None)))

    assert exit_code == 2
    run_dir = tmp_path / "reports" / "run-quick"
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure_category"] == "dataset_error"
    suite = ElementTree.parse(run_dir / "junit.xml").getroot()
    assert suite.attrib["tests"] == "1"
    assert suite.attrib["failures"] == "1"


def test_provider_evidence_gate_fails_before_upload(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, provider_ready=False)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    assert api.asset_by_filename == {}
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert report["provider_evidence"] is None
    assert report["primary_failure"]["category"] == "pipeline_error"


def test_pipeline_failure_archives_the_failed_attempt_before_cleanup(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, fail_chat=True)
    client = httpx.Client(transport=httpx.MockTransport(api))

    exit_code = run_business_regression(_options(tmp_path, manifest, root, "quick"), client=client)

    assert exit_code == 3
    run_dir = tmp_path / "reports" / "run-quick"
    attempts = list((run_dir / "cases").glob("*/*.json"))
    assert len(attempts) == 1
    attempt = json.loads(attempts[0].read_text(encoding="utf-8"))
    assert attempt["failure_category"] == "pipeline_error"
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure_category"] == "pipeline_error"
    assert len(report["cleanup"]) == 6
    suite = ElementTree.parse(run_dir / "junit.xml").getroot()
    assert suite.attrib["failures"] == "1"


def test_intermediate_step_concepts_cannot_satisfy_the_final_answer_gate(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, intermediate_only_concepts=True)
    client = httpx.Client(transport=httpx.MockTransport(api))

    exit_code = run_business_regression(_options(tmp_path, manifest, root, "quick"), client=client)

    assert exit_code == 4
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    first_chat = report["cases"][0]["attempts"][0]["chat"]
    assert "forklift worker near" in first_chat["raw_response"]
    assert first_chat["answer"] == "Unclear scene."
    assert report["cases"][0]["attempts"][0]["answer_evaluation"]["coverage"] == 0.0


def test_incomplete_chat_trace_is_a_pipeline_failure(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, incomplete_chat_trace=True)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert report["primary_failure"]["category"] == "pipeline_error"
    assert "trace evidence is incomplete" in report["primary_failure"]["error"]


def test_same_argument_cached_chat_tool_call_is_not_a_second_execution(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, cached_chat_tool_call=True)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 0
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert all(
        attempt["chat"]["trace"]["video_tool_call_count"] == 2
        for case in report["cases"]
        for attempt in case["attempts"]
    )
    assert all(
        attempt["chat"]["trace"]["video_tool_execution_count"] == 1
        for case in report["cases"]
        for attempt in case["attempts"]
    )


def test_second_chat_tool_execution_is_a_pipeline_failure(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, duplicate_chat_tool_execution=True)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert report["primary_failure"] == {
        "category": "pipeline_error",
        "error": "selected-video Chat trace evidence is incomplete or mismatched",
    }


def test_chunk_upload_failure_still_cleans_the_created_asset(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, fail_upload=True)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    assert set(api.asset_by_filename.values()) == api.deleted
    assert set(api.asset_status.values()) == {"deleted"}
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert report["primary_failure"]["category"] == "pipeline_error"
    assert report["cleanup"][0]["job_id"] is None
    assert report["cleanup"][0]["status"] == "passed"


def test_failed_worker_job_still_cleans_the_created_asset(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, job_status="failed")

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    assert set(api.asset_by_filename.values()) == api.deleted
    report = json.loads((tmp_path / "reports" / "run-quick" / "report.json").read_text(encoding="utf-8"))
    assert report["primary_failure"]["category"] == "pipeline_error"
    assert report["cleanup"][0]["job_id"] in api.job_by_asset.values()


def test_worker_timeout_still_cleans_the_created_asset(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, job_status="running")
    options = _options(tmp_path, manifest, root, "quick")
    options = replace(options, timeout=0.01)

    exit_code = run_business_regression(
        options,
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 3
    assert set(api.asset_by_filename.values()) == api.deleted


def test_primary_and_cleanup_failures_are_both_preserved(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, fail_chat=True, fail_cleanup=True)

    exit_code = run_business_regression(
        _options(tmp_path, manifest, root, "quick"),
        client=httpx.Client(transport=httpx.MockTransport(api)),
    )

    assert exit_code == 5
    report_path = tmp_path / "reports" / "run-quick" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["primary_failure"]["category"] == "pipeline_error"
    assert report["failure_category"] == "cleanup_error"
    assert len(report["cleanup_failures"]) == 6
    suite = ElementTree.parse(report_path.with_name("junit.xml")).getroot()
    failures = {case.attrib["name"] for case in suite.findall("testcase") if case.find("failure") is not None}
    assert "forklift-person-proximity" in failures
    assert "regression-cleanup" in failures
