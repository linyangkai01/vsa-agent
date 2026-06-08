"""Non-empty response validator. Mirrors NVIDIA NonEmptyResponseValidator."""

from typing import Any

from vsa_agent.agents.postprocess.validators.base import BaseValidator
from vsa_agent.agents.postprocess.validators.base import ValidatorResult


class NonEmptyValidator(BaseValidator):
    """Validates that the response is not empty."""

    name = "non_empty_response_validator"

    async def validate(self, output: str, **kwargs: Any) -> ValidatorResult:
        if not output or not output.strip():
            return ValidatorResult(
                name=self.name, passed=False,
                issues=["Response is empty"],
            )
        return ValidatorResult(name=self.name, passed=True)
