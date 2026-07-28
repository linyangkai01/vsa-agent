"""Strict manifest models for the real business-video regression baseline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CORE_SCENARIOS = frozenset(
    {
        "forklift_person_proximity",
        "forklift_safe_separation",
        "worker_close_collaboration",
        "ordinary_worker_activity",
        "ppe_respiratory_controls",
        "ppe_noncompliant",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _non_blank(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


def _https_url(value: str, label: str) -> str:
    normalized = _non_blank(value, label)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an HTTPS URL without credentials")
    return normalized


class LicensePolicy(_StrictModel):
    allowed_license_ids: tuple[str, ...] = Field(min_length=1)
    attribution_required: bool = True

    @field_validator("allowed_license_ids")
    @classmethod
    def validate_license_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value, "license id") for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed license ids must be unique")
        return normalized


class RegressionProfile(_StrictModel):
    source_mode: Literal["clip", "source"]
    attempts: int = Field(ge=1)
    required_passes: int = Field(ge=1)
    top_k: int = Field(ge=1)
    minimum_concept_coverage: float = Field(ge=0.0, le=1.0)
    time_tolerance_sec: float = Field(ge=0.0)
    cleanup_strict: bool = True

    @model_validator(mode="after")
    def validate_pass_count(self) -> RegressionProfile:
        if self.required_passes > self.attempts:
            raise ValueError("required_passes cannot exceed attempts")
        return self


class VideoSource(_StrictModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    filename: str = Field(pattern=r"^[^/\\]+\.(?:mp4|mkv)$")
    source_page_url: str
    download_url: str
    creator: str
    publisher: str
    published_at: date
    license_id: str
    license_url: str
    attribution: str
    retrieved_at: date
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    duration_sec: float = Field(gt=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    codec: str

    @field_validator("source_page_url")
    @classmethod
    def validate_source_page_url(cls, value: str) -> str:
        return _https_url(value, "source_page_url")

    @field_validator("download_url")
    @classmethod
    def validate_download_url(cls, value: str) -> str:
        return _https_url(value, "download_url")

    @field_validator("license_url")
    @classmethod
    def validate_license_url(cls, value: str) -> str:
        return _https_url(value, "license_url")

    @field_validator("creator", "publisher", "license_id", "attribution", "codec")
    @classmethod
    def validate_text_fields(cls, value: str, info) -> str:
        return _non_blank(value, info.field_name)


class ClipSpec(_StrictModel):
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(gt=0.0)
    filename: str = Field(pattern=r"^[^/\\]+\.mp4$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_window(self) -> ClipSpec:
        if self.end_sec <= self.start_sec:
            raise ValueError("clip end_sec must be greater than start_sec")
        return self


class ExpectedWindow(_StrictModel):
    start_sec: float = Field(ge=0.0)
    end_sec: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_window(self) -> ExpectedWindow:
        if self.end_sec <= self.start_sec:
            raise ValueError("expected window end_sec must be greater than start_sec")
        return self


class ConceptGroup(_StrictModel):
    group_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    alternatives: tuple[str, ...] = Field(min_length=1)

    @field_validator("alternatives")
    @classmethod
    def validate_alternatives(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value, "concept alternative") for value in values)
        if len({" ".join(value.casefold().split()) for value in normalized}) != len(normalized):
            raise ValueError("concept alternatives must be unique")
        return normalized


class RequiredConceptGroup(ConceptGroup):
    negated_alternatives: tuple[str, ...] = Field(min_length=1)

    @field_validator("negated_alternatives")
    @classmethod
    def validate_negated_alternatives(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value, "negated concept alternative") for value in values)
        normalized_keys = {" ".join(value.casefold().split()) for value in normalized}
        if len(normalized_keys) != len(normalized):
            raise ValueError("negated concept alternatives must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_positive_and_negated_alternatives(self) -> RequiredConceptGroup:
        alternatives = {" ".join(value.casefold().split()) for value in self.alternatives}
        negated = {" ".join(value.casefold().split()) for value in self.negated_alternatives}
        if alternatives & negated:
            raise ValueError("concept alternatives and negated alternatives must not overlap")
        return self


class ForbiddenConceptGroup(ConceptGroup):
    negated_alternatives: tuple[str, ...] = ()

    @field_validator("negated_alternatives")
    @classmethod
    def validate_negated_alternatives(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value, "negated forbidden alternative") for value in values)
        normalized_keys = {" ".join(value.casefold().split()) for value in normalized}
        if len(normalized_keys) != len(normalized):
            raise ValueError("negated forbidden alternatives must be unique")
        return normalized


class BusinessCase(_StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    scenario: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    clip: ClipSpec
    search_queries: tuple[str, ...] = Field(min_length=1)
    chat_queries: tuple[str, ...] = Field(min_length=1)
    required_concept_groups: tuple[RequiredConceptGroup, ...] = Field(min_length=1)
    forbidden_concept_groups: tuple[ForbiddenConceptGroup, ...] = Field(min_length=1)
    expected_window: ExpectedWindow
    required: bool = True
    tags: tuple[str, ...] = Field(min_length=1)

    @field_validator("search_queries", "chat_queries", "tags")
    @classmethod
    def validate_string_lists(cls, values: tuple[str, ...], info) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value, info.field_name) for value in values)
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError(f"{info.field_name} must contain unique values")
        return normalized

    @model_validator(mode="after")
    def validate_concept_groups(self) -> BusinessCase:
        required_ids = [group.group_id for group in self.required_concept_groups]
        if len(set(required_ids)) != len(required_ids):
            raise ValueError("required concept group ids must be unique")
        forbidden_ids = [group.group_id for group in self.forbidden_concept_groups]
        if len(set(forbidden_ids)) != len(forbidden_ids):
            raise ValueError("forbidden concept group ids must be unique")
        return self


class BusinessBaselineManifest(_StrictModel):
    schema_version: Literal[2]
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    license_policy: LicensePolicy
    profiles: dict[str, RegressionProfile]
    sources: tuple[VideoSource, ...] = Field(min_length=1)
    cases: tuple[BusinessCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> BusinessBaselineManifest:
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("duplicate source_id in manifest")
        source_filenames = [source.filename.casefold() for source in self.sources]
        if len(set(source_filenames)) != len(source_filenames):
            raise ValueError("duplicate source filename in manifest")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("duplicate case_id in manifest")
        clip_filenames = [case.clip.filename.casefold() for case in self.cases]
        if len(set(clip_filenames)) != len(clip_filenames):
            raise ValueError("duplicate clip filename in manifest")

        required_profiles = {"quick", "release", "full"}
        if set(self.profiles) != required_profiles:
            raise ValueError("profiles must contain exactly quick, release, and full")
        quick = self.profiles["quick"]
        release = self.profiles["release"]
        full = self.profiles["full"]
        if (quick.source_mode, quick.attempts, quick.required_passes) != ("clip", 1, 1):
            raise ValueError("quick profile must use one clip attempt with one required pass")
        if (release.source_mode, release.attempts, release.required_passes) != ("clip", 3, 2):
            raise ValueError("release profile must use three clip attempts with two required passes")
        if full.source_mode != "source":
            raise ValueError("full profile must use original sources")

        sources = {source.source_id: source for source in self.sources}
        allowed_licenses = set(self.license_policy.allowed_license_ids)
        for source in self.sources:
            if source.license_id not in allowed_licenses:
                raise ValueError(f"source {source.source_id} license is not allowed")
            if self.license_policy.attribution_required and not source.attribution:
                raise ValueError(f"source {source.source_id} attribution is required")

        scenarios = {case.scenario for case in self.cases if case.required}
        missing = sorted(CORE_SCENARIOS - scenarios)
        if missing:
            raise ValueError(f"missing required core scenarios: {', '.join(missing)}")
        for case in self.cases:
            if case.scenario in CORE_SCENARIOS and not case.required:
                raise ValueError(f"core scenario {case.scenario} must be required")
            source = sources.get(case.source_id)
            if source is None:
                raise ValueError(f"case {case.case_id} references unknown source {case.source_id}")
            if case.clip.end_sec > source.duration_sec:
                raise ValueError(f"case {case.case_id} clip exceeds source duration")
            if case.expected_window.end_sec > source.duration_sec:
                raise ValueError(f"case {case.case_id} expected window exceeds source duration")
        return self

    def source_by_id(self, source_id: str) -> VideoSource:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise KeyError(source_id)


def load_business_manifest(path: Path) -> BusinessBaselineManifest:
    """Load and strictly validate one YAML business-video manifest."""

    manifest_path = Path(path).resolve(strict=True)
    if not manifest_path.is_file():
        raise ValueError("business baseline manifest must be a regular file")
    try:
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"business baseline manifest YAML is invalid: {error}") from None
    if not isinstance(payload, dict):
        raise ValueError("business baseline manifest root must be a mapping")
    return BusinessBaselineManifest.model_validate(payload)


__all__ = [
    "CORE_SCENARIOS",
    "BusinessBaselineManifest",
    "BusinessCase",
    "ClipSpec",
    "ConceptGroup",
    "ExpectedWindow",
    "ForbiddenConceptGroup",
    "LicensePolicy",
    "RegressionProfile",
    "RequiredConceptGroup",
    "VideoSource",
    "load_business_manifest",
]
