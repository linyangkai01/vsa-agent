"""Real-provider business-video regression orchestration and evidence reports."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx

from vsa_agent.evaluators.business_baseline_eval import (
    evaluate_business_answer,
    evaluate_business_attempts,
    evaluate_business_search,
)
from vsa_agent.recorded_video.business_manifest import (
    BusinessBaselineManifest,
    BusinessCase,
    RegressionProfile,
    load_business_manifest,
)
from vsa_agent.recorded_video.business_preparation import sha256_file
from vsa_agent.recorded_video.production_acceptance import (
    AcceptanceCase,
    JobIdentity,
    ProductionApiClient,
    ValidationError,
    atomic_write_json,
)
from vsa_agent.tools.search import SearchOutput

LOGGER = logging.getLogger(__name__)
FailureCategory = Literal["dataset_error", "pipeline_error", "accuracy_failure", "cleanup_error"]
EXIT_CODES: dict[str | None, int] = {
    None: 0,
    "dataset_error": 2,
    "pipeline_error": 3,
    "accuracy_failure": 4,
    "cleanup_error": 5,
}
_TRANSIENT_STATUS = frozenset({429, 502, 503, 504})


class BusinessRegressionError(RuntimeError):
    def __init__(self, category: FailureCategory, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True, slots=True)
class BusinessRegressionOptions:
    manifest: Path
    data_root: Path
    profile: str
    api_url: str
    ui_url: str
    output_root: Path
    timeout: float = 900.0
    poll_interval: float = 1.0
    request_attempts: int = 3
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.timeout <= 0 or self.poll_interval <= 0 or self.request_attempts < 1:
            raise ValueError("timeouts and request attempts must be positive")
        for label, value in (("api_url", self.api_url), ("ui_url", self.ui_url)):
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"{label} must be an HTTP(S) origin")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(f"{label} must not contain credentials, query, or fragment")
        if self.run_id is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", self.run_id):
            raise ValueError("run_id contains unsupported characters")
        object.__setattr__(self, "manifest", Path(self.manifest).resolve(strict=False))
        object.__setattr__(self, "data_root", Path(self.data_root).resolve(strict=False))
        object.__setattr__(self, "output_root", Path(self.output_root).resolve(strict=False))
        object.__setattr__(self, "api_url", self.api_url.rstrip("/"))
        object.__setattr__(self, "ui_url", self.ui_url.rstrip("/"))


@dataclass(frozen=True, slots=True)
class _AssetRun:
    key: str
    path: Path
    sha256: str
    anchor: datetime
    job: JobIdentity


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else "unknown"


def _configure_logging(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("vsa_agent.recorded_video.business_regression")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler


def _selected_path(
    manifest: BusinessBaselineManifest,
    case: BusinessCase,
    root: Path,
    profile: RegressionProfile,
) -> Path:
    if profile.source_mode == "clip":
        return root / "clips" / case.clip.filename
    return root / "sources" / manifest.source_by_id(case.source_id).filename


def _selected_sha(manifest: BusinessBaselineManifest, case: BusinessCase, profile: RegressionProfile) -> str:
    return case.clip.sha256 if profile.source_mode == "clip" else manifest.source_by_id(case.source_id).sha256


def _asset_key(case: BusinessCase, profile: RegressionProfile) -> str:
    return case.case_id if profile.source_mode == "clip" else case.source_id


def _validate_dataset(
    manifest: BusinessBaselineManifest,
    root: Path,
    profile: RegressionProfile,
) -> dict[str, tuple[Path, str]]:
    selected: dict[str, tuple[Path, str]] = {}
    for case in manifest.cases:
        path = _selected_path(manifest, case, root, profile)
        expected = _selected_sha(manifest, case, profile)
        key = _asset_key(case, profile)
        if not path.is_file():
            raise BusinessRegressionError("dataset_error", f"required business video is missing: {path}")
        observed = sha256_file(path)
        if observed != expected:
            raise BusinessRegressionError(
                "dataset_error",
                f"business video sha256 mismatch for {path.name}: expected {expected}, observed {observed}",
            )
        previous = selected.get(key)
        if previous is not None and previous != (path, expected):
            raise BusinessRegressionError("dataset_error", f"asset key {key} resolves to conflicting files")
        selected[key] = (path, expected)
    return selected


def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        raise BusinessRegressionError("pipeline_error", f"{operation} returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise BusinessRegressionError("pipeline_error", f"{operation} response must be a JSON object")
    return payload


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int,
    expected: set[int],
    **kwargs: Any,
) -> tuple[httpx.Response, int]:
    retries = 0
    for request_number in range(1, attempts + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            if request_number == attempts:
                raise BusinessRegressionError("pipeline_error", f"{method} {url} failed: {error}") from None
            retries += 1
            time.sleep(min(0.25 * request_number, 1.0))
            continue
        if response.status_code in expected:
            return response, retries
        if response.status_code in _TRANSIENT_STATUS and request_number < attempts:
            retries += 1
            time.sleep(min(0.25 * request_number, 1.0))
            continue
        detail = response.text.strip()[:500]
        raise BusinessRegressionError(
            "pipeline_error",
            f"{method} {url} returned HTTP {response.status_code}: {detail}",
        )
    raise AssertionError("unreachable request retry state")


def _search(
    client: httpx.Client,
    options: BusinessRegressionOptions,
    case: BusinessCase,
    profile: RegressionProfile,
    asset: _AssetRun,
) -> tuple[SearchOutput, int]:
    response, retries = _request(
        client,
        "POST",
        f"{options.ui_url}/api/v1/search",
        attempts=options.request_attempts,
        expected={200},
        json={
            "query": case.search_queries[0],
            "source_type": "video_file",
            "video_sources": [asset.path.name],
            "top_k": profile.top_k,
            "min_cosine_similarity": 0.0,
            "agent_mode": False,
        },
    )
    try:
        return SearchOutput.model_validate(_response_json(response, "business search")), retries
    except ValueError as error:
        raise BusinessRegressionError("pipeline_error", f"business search response is invalid: {error}") from None


def _expected_window(asset: _AssetRun, case: BusinessCase, profile: RegressionProfile) -> tuple[datetime, datetime]:
    if profile.source_mode == "clip":
        start_offset = 0.0
        end_offset = case.clip.end_sec - case.clip.start_sec
    else:
        start_offset = case.expected_window.start_sec
        end_offset = case.expected_window.end_sec
    return asset.anchor + timedelta(seconds=start_offset), asset.anchor + timedelta(seconds=end_offset)


def _matched_result(output: SearchOutput, asset_id: str, segment_id: str | None) -> dict[str, Any]:
    for result in output.data:
        if (result.asset_id or result.sensor_id) == asset_id and (
            segment_id is None or result.segment_id == segment_id
        ):
            return result.model_dump(mode="json")
    raise BusinessRegressionError("accuracy_failure", f"search result for asset {asset_id} is unavailable")


def _check_media(
    client: httpx.Client,
    options: BusinessRegressionOptions,
    asset: _AssetRun,
    match: dict[str, Any],
) -> dict[str, Any]:
    screenshot = match.get("screenshot_url")
    parsed = urlsplit(screenshot) if isinstance(screenshot, str) else None
    if parsed is None or not screenshot.startswith("/") or parsed.scheme or parsed.netloc:
        raise BusinessRegressionError("pipeline_error", "search result thumbnail URL is not same-origin")
    thumbnail, thumbnail_retries = _request(
        client,
        "GET",
        urljoin(options.ui_url + "/", screenshot.lstrip("/")),
        attempts=options.request_attempts,
        expected={200},
    )
    if not thumbnail.content:
        raise BusinessRegressionError("pipeline_error", "search result thumbnail is empty")
    media, media_retries = _request(
        client,
        "GET",
        f"{options.ui_url}/api/v1/vst/v1/storage/file/{asset.job.asset_id}",
        attempts=options.request_attempts,
        expected={206},
        headers={"Range": "bytes=0-0"},
    )
    content_range = media.headers.get("Content-Range", "")
    if media.headers.get("Accept-Ranges", "").lower() != "bytes" or not re.fullmatch(
        r"bytes 0-0/[1-9][0-9]*", content_range
    ):
        raise BusinessRegressionError("pipeline_error", "recorded-video Range response is invalid")
    if len(media.content) != 1:
        raise BusinessRegressionError("pipeline_error", "recorded-video Range response must contain one byte")
    return {
        "thumbnail_url": screenshot,
        "thumbnail_bytes": len(thumbnail.content),
        "content_range": content_range,
        "http_retries": thumbnail_retries + media_retries,
    }


def _chat(
    client: httpx.Client,
    options: BusinessRegressionOptions,
    case: BusinessCase,
    asset: _AssetRun,
    match: dict[str, Any],
) -> tuple[str, str, int, str, str]:
    context = {
        "assetId": asset.job.asset_id,
        "segmentId": match["segment_id"],
        "jobId": asset.job.job_id,
        "sensorId": asset.job.asset_id,
        "videoName": match["video_name"],
        "startTime": match["start_time"],
        "endTime": match["end_time"],
        "mediaType": "recorded-video-segment",
    }
    content = f"[Context: {json.dumps([context], ensure_ascii=False, separators=(',', ':'))}]\n{case.chat_queries[0]}"
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    response, retries = _request(
        client,
        "POST",
        f"{options.ui_url}/api/chat",
        attempts=options.request_attempts,
        expected={200},
        headers={"Conversation-Id": conversation_id, "User-Message-ID": message_id},
        json={
            "chatCompletionURL": f"{options.api_url}/chat/stream",
            "messages": [{"role": "user", "content": content}],
            "additionalProps": {"enableIntermediateSteps": True},
        },
    )
    raw_response = response.text.strip()
    answer = re.sub(
        r"<intermediatestep>.*?</intermediatestep>",
        "",
        raw_response,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    if not answer or re.search(r"(?i)(^|\b)error\s*:", answer):
        raise BusinessRegressionError("pipeline_error", "selected-video Chat returned no usable answer")
    return answer, raw_response, retries, conversation_id, message_id


def _cleanup_asset(client: httpx.Client, options: BusinessRegressionOptions, asset: _AssetRun) -> dict[str, Any]:
    deadline = time.monotonic() + min(options.timeout, 120.0)
    retries = 0
    while True:
        response, request_retries = _request(
            client,
            "DELETE",
            f"{options.ui_url}/api/v1/videos/{asset.job.asset_id}",
            attempts=options.request_attempts,
            expected={202, 204, 404, 410},
        )
        retries += request_retries
        if response.status_code in {204, 404, 410}:
            break
        if time.monotonic() >= deadline:
            raise BusinessRegressionError("cleanup_error", f"asset {asset.job.asset_id} deletion timed out")
        time.sleep(options.poll_interval)
    media, media_retries = _request(
        client,
        "GET",
        f"{options.ui_url}/api/v1/vst/v1/storage/file/{asset.job.asset_id}",
        attempts=options.request_attempts,
        expected={404, 410},
        headers={"Range": "bytes=0-0"},
    )
    return {
        "asset_id": asset.job.asset_id,
        "status": "passed",
        "delete_status": response.status_code,
        "media_status": media.status_code,
        "http_retries": retries + media_retries,
    }


def _write_attempt(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _write_junit(path: Path, report: dict[str, Any]) -> None:
    cases = list(report.get("cases", []))
    failure_category = report.get("failure_category")
    if (
        report.get("status") != "passed"
        and failure_category
        and not any(case.get("failure_category") == failure_category for case in cases)
    ):
        cases.append(
            {
                "case_id": "regression-setup",
                "status": "failed",
                "failure_category": failure_category,
                "error": report.get("error"),
            }
        )
    failures = sum(1 for case in cases if case.get("status") != "passed")
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "business-video-regression",
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": "0",
            "skipped": "0",
        },
    )
    for case in cases:
        node = ElementTree.SubElement(
            suite,
            "testcase",
            {"classname": "business_video", "name": str(case.get("case_id", "unknown"))},
        )
        if case.get("status") != "passed":
            failure = ElementTree.SubElement(
                node,
                "failure",
                {
                    "type": str(case.get("failure_category") or report.get("failure_category") or "failure"),
                    "message": str(case.get("error") or "business gate failed"),
                },
            )
            failure.text = json.dumps(case, ensure_ascii=False, sort_keys=True)
        output = ElementTree.SubElement(node, "system-out")
        output.text = json.dumps(case, ensure_ascii=False, sort_keys=True)
    tree = ElementTree.ElementTree(suite)
    ElementTree.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(path)


def _execute_attempt(
    client: httpx.Client,
    options: BusinessRegressionOptions,
    profile: RegressionProfile,
    case: BusinessCase,
    asset: _AssetRun,
    number: int,
    started: float,
) -> tuple[dict[str, Any], Any | None]:
    output, search_retries = _search(client, options, case, profile, asset)
    expected_start, expected_end = _expected_window(asset, case, profile)
    search_evaluation = evaluate_business_search(
        output,
        expected_asset_id=asset.job.asset_id,
        expected_start=expected_start,
        expected_end=expected_end,
        top_k=profile.top_k,
        tolerance_sec=profile.time_tolerance_sec,
    )
    if not search_evaluation.passed:
        return (
            {
                "case_id": case.case_id,
                "attempt": number,
                "status": "failed",
                "failure_category": "accuracy_failure",
                "search": output.model_dump(mode="json"),
                "search_evaluation": search_evaluation.model_dump(mode="json"),
                "http_retries": search_retries,
                "duration_sec": time.monotonic() - started,
            },
            None,
        )
    match = _matched_result(output, asset.job.asset_id, search_evaluation.matched_segment_id)
    media = _check_media(client, options, asset, match)
    answer, raw_response, chat_retries, conversation_id, message_id = _chat(client, options, case, asset, match)
    answer_evaluation = evaluate_business_answer(
        answer,
        case.required_concept_groups,
        case.forbidden_concepts,
        minimum_coverage=profile.minimum_concept_coverage,
    )
    return (
        {
            "case_id": case.case_id,
            "attempt": number,
            "status": "passed" if answer_evaluation.passed else "failed",
            "failure_category": None if answer_evaluation.passed else "accuracy_failure",
            "asset_id": asset.job.asset_id,
            "job_id": asset.job.job_id,
            "search": output.model_dump(mode="json"),
            "search_evaluation": search_evaluation.model_dump(mode="json"),
            "media": media,
            "chat": {
                "conversation_id": conversation_id,
                "user_message_id": message_id,
                "raw_response": raw_response,
                "answer": answer,
            },
            "answer_evaluation": answer_evaluation.model_dump(mode="json"),
            "http_retries": search_retries + media["http_retries"] + chat_retries,
            "duration_sec": time.monotonic() - started,
        },
        answer_evaluation,
    )


def _run_case(
    client: httpx.Client,
    options: BusinessRegressionOptions,
    profile: RegressionProfile,
    case: BusinessCase,
    asset: _AssetRun,
    run_dir: Path,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    answer_evaluations = []
    for number in range(1, profile.attempts + 1):
        started = time.monotonic()
        try:
            payload, answer_evaluation = _execute_attempt(
                client,
                options,
                profile,
                case,
                asset,
                number,
                started,
            )
        except BusinessRegressionError as error:
            payload = {
                "case_id": case.case_id,
                "attempt": number,
                "status": "failed",
                "failure_category": error.category,
                "error": error.message,
                "duration_sec": time.monotonic() - started,
            }
            _write_attempt(run_dir / "cases" / case.case_id / f"{number}.json", payload)
            raise
        _write_attempt(run_dir / "cases" / case.case_id / f"{number}.json", payload)
        attempts.append(payload)
        if answer_evaluation is not None:
            answer_evaluations.append(answer_evaluation)

    if len(answer_evaluations) == profile.attempts:
        aggregate = evaluate_business_attempts(tuple(answer_evaluations), required_passes=profile.required_passes)
        passed = aggregate.passed and all(item["search_evaluation"]["passed"] for item in attempts)
        aggregate_payload: dict[str, Any] = aggregate.model_dump(mode="json")
    else:
        passed = False
        aggregate_payload = {
            "attempt_count": profile.attempts,
            "required_passes": profile.required_passes,
            "pass_count": sum(item["status"] == "passed" for item in attempts),
            "forbidden_attempts": [],
            "passed": False,
        }
    return {
        "case_id": case.case_id,
        "scenario": case.scenario,
        "required": case.required,
        "status": "passed" if passed else "failed",
        "failure_category": None if passed else "accuracy_failure",
        "asset_id": asset.job.asset_id,
        "job_id": asset.job.job_id,
        "attempts": attempts,
        "aggregate": aggregate_payload,
    }


def run_business_regression(
    options: BusinessRegressionOptions,
    *,
    client: httpx.Client | None = None,
) -> int:
    """Run an already-started production stack and always emit JSON/JUnit evidence."""

    run_id = options.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-{uuid.uuid4().hex[:8]}"
    run_dir = options.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    log_handler = _configure_logging(run_dir / "runner.log")
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": _timestamp(),
        "finished_at": None,
        "git_commit": _git_commit(),
        "profile": options.profile,
        "dataset": None,
        "status": "failed",
        "failure_category": None,
        "error": None,
        "cases": [],
        "assets": [],
        "cleanup": [],
    }
    owns_client = client is None
    shared_client = client or httpx.Client(timeout=options.timeout, follow_redirects=False)
    assets: dict[str, _AssetRun] = {}
    exit_code = EXIT_CODES["pipeline_error"]
    try:
        manifest = load_business_manifest(options.manifest)
        profile = manifest.profiles.get(options.profile)
        if profile is None:
            raise BusinessRegressionError("dataset_error", f"unknown regression profile: {options.profile}")
        report["dataset"] = {
            "id": manifest.dataset_id,
            "version": manifest.dataset_version,
            "manifest": str(options.manifest),
        }
        selected = _validate_dataset(manifest, options.data_root, profile)
        LOGGER.info(
            "business_regression.start run_id=%s profile=%s cases=%d assets=%d",
            run_id,
            options.profile,
            len(manifest.cases),
            len(selected),
        )
        api_client = ProductionApiClient(
            options.api_url,
            client=shared_client,
            request_timeout=options.timeout,
            poll_interval=options.poll_interval,
        )
        for key, (path, sha256) in selected.items():
            anchor = datetime.now(UTC)
            job = api_client.create_and_complete(AcceptanceCase(path=path, query="business regression", sha256=sha256))
            snapshot = api_client.wait_job(job, options.timeout)
            assets[key] = _AssetRun(key=key, path=path, sha256=sha256, anchor=anchor, job=job)
            report["assets"].append(
                {
                    "key": key,
                    "path": str(path),
                    "sha256": sha256,
                    "asset_id": job.asset_id,
                    "job_id": job.job_id,
                    "anchor": anchor.isoformat().replace("+00:00", "Z"),
                    "job_status": asdict(snapshot),
                }
            )
        for case in manifest.cases:
            try:
                result = _run_case(
                    client=shared_client,
                    options=options,
                    profile=profile,
                    case=case,
                    asset=assets[_asset_key(case, profile)],
                    run_dir=run_dir,
                )
            except BusinessRegressionError as error:
                report["cases"].append(
                    {
                        "case_id": case.case_id,
                        "scenario": case.scenario,
                        "required": case.required,
                        "status": "failed",
                        "failure_category": error.category,
                        "error": error.message,
                        "asset_id": assets[_asset_key(case, profile)].job.asset_id,
                        "job_id": assets[_asset_key(case, profile)].job.job_id,
                    }
                )
                raise
            report["cases"].append(result)
        failed = [case for case in report["cases"] if case["status"] != "passed"]
        if failed:
            raise BusinessRegressionError(
                "accuracy_failure",
                "business accuracy gates failed: " + ", ".join(case["case_id"] for case in failed),
            )
        report["status"] = "passed"
        exit_code = 0
    except BusinessRegressionError as error:
        report["failure_category"] = error.category
        report["error"] = error.message
        exit_code = EXIT_CODES[error.category]
        LOGGER.exception("business_regression.failed category=%s", error.category)
    except (OSError, ValueError) as error:
        report["failure_category"] = "dataset_error"
        report["error"] = str(error)
        exit_code = EXIT_CODES["dataset_error"]
        LOGGER.exception("business_regression.failed category=dataset_error")
    except (ValidationError, httpx.HTTPError) as error:
        report["failure_category"] = "pipeline_error"
        report["error"] = str(error)
        exit_code = EXIT_CODES["pipeline_error"]
        LOGGER.exception("business_regression.failed category=pipeline_error")
    except Exception:
        report["failure_category"] = "pipeline_error"
        report["error"] = "unexpected regression error; inspect runner.log"
        exit_code = EXIT_CODES["pipeline_error"]
        LOGGER.exception("business_regression.failed category=pipeline_error")
    finally:
        cleanup_errors: list[str] = []
        for asset in reversed(tuple(assets.values())):
            try:
                report["cleanup"].append(_cleanup_asset(shared_client, options, asset))
            except Exception as error:
                cleanup_errors.append(f"{asset.job.asset_id}: {error}")
                report["cleanup"].append({"asset_id": asset.job.asset_id, "status": "failed", "error": str(error)})
                LOGGER.exception("business_regression.cleanup_failed asset_id=%s", asset.job.asset_id)
        if cleanup_errors:
            report["status"] = "failed"
            report["failure_category"] = "cleanup_error"
            report["error"] = "; ".join(cleanup_errors)
            exit_code = EXIT_CODES["cleanup_error"]
        report["finished_at"] = _timestamp()
        atomic_write_json(run_dir / "report.json", report)
        _write_junit(run_dir / "junit.xml", report)
        if owns_client:
            shared_client.close()
        logger = logging.getLogger("vsa_agent.recorded_video.business_regression")
        logger.removeHandler(log_handler)
        log_handler.close()
    return exit_code


__all__ = [
    "BusinessRegressionError",
    "BusinessRegressionOptions",
    "EXIT_CODES",
    "run_business_regression",
]
