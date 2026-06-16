"""Tests for agents/postprocessing/pipeline.py."""
import pytest
from vsa_agent.agents.postprocessing.pipeline import ValidationPipeline, PostprocessingResult
from vsa_agent.agents.postprocessing.validators.base import BaseValidator, ValidatorResult

class TestPostprocessingResult:
    def test_defaults(self):
        pr = PostprocessingResult(passed=True)
        assert pr.passed is True
        assert pr.feedback == ""

class TestValidatorResult:
    def test_defaults(self):
        vr = ValidatorResult(name="test", passed=True)
        assert vr.passed is True
        assert vr.issues == []

class TestNonEmptyValidator:
    async def test_empty_output_fails(self):
        from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
        validator = NonEmptyValidator()
        result = await validator.validate("")
        assert result.passed is False

    async def test_non_empty_passes(self):
        from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
        validator = NonEmptyValidator()
        result = await validator.validate("some content")
        assert result.passed is True

class TestURLValidator:
    async def test_valid_urls_pass(self):
        from vsa_agent.agents.postprocessing.validators.url_check import URLValidator
        validator = URLValidator()
        result = await validator.validate("Check https://example.com")
        assert result.passed is True

class TestSafetyChecklistValidator:
    async def test_safety_keywords_pass(self):
        from vsa_agent.agents.postprocessing.validators.safety_checklist import SafetyChecklistValidator
        validator = SafetyChecklistValidator()
        result = await validator.validate("Safety inspection passed")
        assert result.passed is True

    async def test_no_keywords_fails(self):
        from vsa_agent.agents.postprocessing.validators.safety_checklist import SafetyChecklistValidator
        validator = SafetyChecklistValidator()
        result = await validator.validate("Just a random observation")
        assert result.passed is False

class TestValidationPipeline:
    async def test_all_validators_pass(self):
        from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
        pipeline = ValidationPipeline([NonEmptyValidator()])
        result = await pipeline.process("Valid content")
        assert result.passed is True

    async def test_first_failure_stops(self):
        from vsa_agent.agents.postprocessing.validators.non_empty import NonEmptyValidator
        pipeline = ValidationPipeline([NonEmptyValidator()])
        result = await pipeline.process("")
        assert result.passed is False

    async def test_empty_validator_list(self):
        pipeline = ValidationPipeline([])
        result = await pipeline.process("any content")
        assert result.passed is True
