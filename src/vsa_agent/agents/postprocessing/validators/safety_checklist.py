"""Safety report checklist validator."""

from typing import Any

from vsa_agent.agents.postprocessing.validators.base import BaseValidator, ValidatorResult

SAFETY_KEYWORDS = ["hard hat", "safety", "PPE", "violation", "helmet", "red zone", "forklift"]


class SafetyChecklistValidator(BaseValidator):
    """Checks output contains safety-related findings."""

    name = "safety_checklist_validator"

    async def validate(self, output: str, **kwargs: Any) -> ValidatorResult:
        if not output or not output.strip():
            return ValidatorResult(name=self.name, passed=True)
        found = [kw for kw in SAFETY_KEYWORDS if kw.lower() in output.lower()]
        if not found:
            return ValidatorResult(
                name=self.name,
                passed=False,
                issues=["No safety keywords found in output"],
            )
        return ValidatorResult(name=self.name, passed=True)
