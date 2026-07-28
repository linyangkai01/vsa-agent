from __future__ import annotations

import hashlib
import json
import uuid
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
    ) -> None:
        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        self.file_sizes = {
            case["clip"]["filename"]: (root / "clips" / case["clip"]["filename"]).stat().st_size
            for case in payload["cases"]
        }
        self.asset_by_filename: dict[str, str] = {}
        self.job_by_asset: dict[str, str] = {}
        self.deleted: set[str] = set()
        self.chat_calls = 0
        self.transient_chat = transient_chat
        self.fail_chat = fail_chat
        self.intermediate_only_concepts = intermediate_only_concepts

    def _json(self, request: httpx.Request) -> dict[str, object]:
        return json.loads(request.content.decode())

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/videos":
            filename = str(self._json(request)["filename"])
            asset_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            self.asset_by_filename[filename] = asset_id
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
            job_id = str(uuid.uuid4())
            self.job_by_asset[asset_id] = job_id
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
                    "status": "completed",
                    "stage": "publish",
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
            if self.intermediate_only_concepts:
                return httpx.Response(
                    200,
                    text=(
                        '<intermediatestep>{"content":{"payload":"forklift worker near PPE working"}}'
                        "</intermediatestep>Unclear scene."
                    ),
                )
            answer = (
                "A forklift and workers are near each other with a safe distance. Multiple people are working "
                "together in a routine surveying task. PPE and protective equipment are properly worn in the "
                "compliant scene; the noncompliant scene shows missing or incorrectly used equipment."
            )
            return httpx.Response(200, text=answer)
        delete = re_fullmatch(r"/api/v1/videos/([^/]+)", path)
        if request.method == "DELETE" and delete:
            self.deleted.add(delete.group(1))
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


def test_release_http_retry_does_not_create_a_provider_attempt(tmp_path: Path) -> None:
    manifest, root = _dataset(tmp_path)
    api = _BusinessApi(manifest, root, transient_chat=True)
    client = httpx.Client(transport=httpx.MockTransport(api))

    exit_code = run_business_regression(_options(tmp_path, manifest, root, "release"), client=client)

    assert exit_code == 0
    report = json.loads((tmp_path / "reports" / "run-release" / "report.json").read_text(encoding="utf-8"))
    assert sum(len(case["attempts"]) for case in report["cases"]) == 18
    assert api.chat_calls == 19
    assert report["cases"][0]["attempts"][0]["http_retries"] == 1


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
