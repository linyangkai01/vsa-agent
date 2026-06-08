import asyncio
import pytest
from vsa_agent.agents.postprocess.pipeline import ValidationPipeline
from vsa_agent.agents.postprocess.validators.base import ValidatorResult
from vsa_agent.agents.postprocess.validators.non_empty import NonEmptyValidator
from vsa_agent.agents.postprocess.validators.url_check import URLValidator
from vsa_agent.agents.postprocess.validators.safety_checklist import SafetyChecklistValidator


class TestNonEmptyValidator:
    def test_empty_output_fails(self):
        result = asyncio.run(NonEmptyValidator().validate(''))
        assert not result.passed
    def test_non_empty_output_passes(self):
        result = asyncio.run(NonEmptyValidator().validate('Report'))
        assert result.passed

class TestURLValidator:
    def test_no_urls_passes(self):
        result = asyncio.run(URLValidator().validate('Plain text'))
        assert result.passed
    def test_valid_url_passes(self):
        result = asyncio.run(URLValidator().validate('https://ex.com'))
        assert result.passed

class TestSafetyChecklistValidator:
    def test_empty_output_skips(self):
        result = asyncio.run(SafetyChecklistValidator().validate(''))
        assert result.passed
    def test_checks_for_safety_items(self):
        result = asyncio.run(SafetyChecklistValidator().validate('Worker without hard hat'))
        assert isinstance(result, ValidatorResult)

class TestValidationPipeline:
    def test_all_pass(self):
        pipeline = ValidationPipeline([NonEmptyValidator(), URLValidator()])
        result = asyncio.run(pipeline.process('Valid report'))
        assert result.passed
    def test_first_validator_fails(self):
        pipeline = ValidationPipeline([NonEmptyValidator()])
        result = asyncio.run(pipeline.process(''))
        assert not result.passed
    def test_empty_pipeline_passes(self):
        result = asyncio.run(ValidationPipeline([]).process('anything'))
        assert result.passed
