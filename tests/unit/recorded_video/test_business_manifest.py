from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from vsa_agent.recorded_video.business_manifest import BusinessBaselineManifest, load_business_manifest


def _manifest_payload() -> dict[str, object]:
    source = {
        "source_id": "forklift-safety",
        "filename": "forklift-safety.mp4",
        "source_page_url": "https://archive.org/details/forklift-safety",
        "download_url": "https://archive.org/download/forklift-safety/video.mp4",
        "creator": "State safety agency",
        "publisher": "PublicResourceOrg",
        "published_at": "2003-01-01",
        "license_id": "CC-BY-3.0",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "attribution": "State safety agency, CC BY 3.0",
        "retrieved_at": "2026-07-28",
        "sha256": "a" * 64,
        "size_bytes": 1000,
        "duration_sec": 120.0,
        "width": 1280,
        "height": 720,
        "codec": "h264",
    }
    scenarios = (
        "forklift_person_proximity",
        "forklift_safe_separation",
        "worker_close_collaboration",
        "ordinary_worker_activity",
        "ppe_respiratory_controls",
        "ppe_noncompliant",
    )
    cases = []
    for index, scenario in enumerate(scenarios):
        cases.append(
            {
                "case_id": scenario.replace("_", "-"),
                "source_id": "forklift-safety",
                "scenario": scenario,
                "clip": {
                    "start_sec": float(index * 10),
                    "end_sec": float(index * 10 + 8),
                    "filename": f"{scenario}.mp4",
                    "sha256": "b" * 64,
                },
                "search_queries": ["forklift near worker"],
                "chat_queries": ["Describe the safety situation."],
                "required_concept_groups": [
                    {
                        "group_id": "person",
                        "alternatives": ["person", "worker"],
                        "negated_alternatives": ["no person", "no worker"],
                    },
                    {
                        "group_id": "vehicle",
                        "alternatives": ["forklift", "lift truck"],
                        "negated_alternatives": ["no forklift", "no lift truck"],
                    },
                ],
                "forbidden_concept_groups": [
                    {
                        "group_id": "no_people",
                        "alternatives": ["no people are present", "nobody is present"],
                    }
                ],
                "expected_window": {"start_sec": float(index * 10), "end_sec": float(index * 10 + 8)},
                "required": True,
                "tags": ["real-video", scenario],
            }
        )
    return {
        "schema_version": 2,
        "dataset_id": "vsa-industrial-safety-real",
        "dataset_version": "1.1.0",
        "license_policy": {
            "allowed_license_ids": ["CC-BY-3.0"],
            "attribution_required": True,
        },
        "profiles": {
            "quick": {
                "source_mode": "clip",
                "attempts": 1,
                "required_passes": 1,
                "top_k": 5,
                "minimum_concept_coverage": 0.8,
                "time_tolerance_sec": 5.0,
                "cleanup_strict": True,
            },
            "release": {
                "source_mode": "clip",
                "attempts": 3,
                "required_passes": 2,
                "top_k": 5,
                "minimum_concept_coverage": 0.8,
                "time_tolerance_sec": 5.0,
                "cleanup_strict": True,
            },
            "full": {
                "source_mode": "source",
                "attempts": 1,
                "required_passes": 1,
                "top_k": 5,
                "minimum_concept_coverage": 0.8,
                "time_tolerance_sec": 5.0,
                "cleanup_strict": True,
            },
        },
        "sources": [source],
        "cases": cases,
    }


def test_manifest_accepts_the_six_required_business_scenarios() -> None:
    manifest = BusinessBaselineManifest.model_validate(_manifest_payload())

    assert manifest.schema_version == 2
    assert len(manifest.cases) == 6
    assert manifest.profiles["release"].required_passes == 2


def test_manifest_rejects_unknown_fields() -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="unexpected"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_missing_core_scenario() -> None:
    payload = _manifest_payload()
    payload["cases"] = payload["cases"][:-1]

    with pytest.raises(ValidationError, match="missing required core scenarios"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_unapproved_license() -> None:
    payload = _manifest_payload()
    payload["sources"][0]["license_id"] = "ARR"

    with pytest.raises(ValidationError, match="license is not allowed"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_clip_outside_source_duration() -> None:
    payload = _manifest_payload()
    payload["cases"][0]["clip"]["end_sec"] = 121.0

    with pytest.raises(ValidationError, match="exceeds source duration"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_invalid_sha256() -> None:
    payload = _manifest_payload()
    payload["sources"][0]["sha256"] = "not-a-hash"

    with pytest.raises(ValidationError, match="sha256"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_schema_v1_and_flat_forbidden_concepts() -> None:
    payload = _manifest_payload()
    payload["schema_version"] = 1
    case = payload["cases"][0]
    case["forbidden_concepts"] = ["no people are present"]
    case.pop("forbidden_concept_groups")

    with pytest.raises(ValidationError, match="schema_version|forbidden_concepts"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_requires_negated_alternatives_for_every_required_group() -> None:
    payload = _manifest_payload()
    payload["cases"][0]["required_concept_groups"][0].pop("negated_alternatives")

    with pytest.raises(ValidationError, match="negated_alternatives"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_empty_forbidden_concept_group() -> None:
    payload = _manifest_payload()
    payload["cases"][0]["forbidden_concept_groups"][0]["alternatives"] = []

    with pytest.raises(ValidationError, match="alternatives"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_duplicate_forbidden_group_ids() -> None:
    payload = _manifest_payload()
    duplicate = copy.deepcopy(payload["cases"][0]["forbidden_concept_groups"][0])
    duplicate["alternatives"] = ["the work area is empty"]
    payload["cases"][0]["forbidden_concept_groups"].append(duplicate)

    with pytest.raises(ValidationError, match="forbidden concept group ids must be unique"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_release_profile_that_can_pass_one_of_three() -> None:
    payload = _manifest_payload()
    payload["profiles"]["release"]["required_passes"] = 1

    with pytest.raises(ValidationError, match="release profile"):
        BusinessBaselineManifest.model_validate(payload)


def test_load_manifest_reads_yaml_and_resolves_source_lookup(tmp_path: Path) -> None:
    import yaml

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(_manifest_payload(), sort_keys=False), encoding="utf-8")

    manifest = load_business_manifest(manifest_path)

    assert manifest.source_by_id("forklift-safety").filename == "forklift-safety.mp4"


def test_manifest_rejects_duplicate_case_id() -> None:
    payload = copy.deepcopy(_manifest_payload())
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]

    with pytest.raises(ValidationError, match="duplicate case_id"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_duplicate_source_filename() -> None:
    payload = copy.deepcopy(_manifest_payload())
    duplicate = copy.deepcopy(payload["sources"][0])
    duplicate["source_id"] = "second-source"
    duplicate["filename"] = "FORKLIFT-SAFETY.mp4"
    payload["sources"].append(duplicate)

    with pytest.raises(ValidationError, match="duplicate source filename"):
        BusinessBaselineManifest.model_validate(payload)


def test_manifest_rejects_duplicate_clip_filename() -> None:
    payload = copy.deepcopy(_manifest_payload())
    payload["cases"][1]["clip"]["filename"] = "FORKLIFT_PERSON_PROXIMITY.mp4"

    with pytest.raises(ValidationError, match="duplicate clip filename"):
        BusinessBaselineManifest.model_validate(payload)
