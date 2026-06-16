"""Validation pipeline — runs validators in sequence. Mirrors NVIDIA PostprocessingNode."""

import logging

from pydantic import BaseModel
from pydantic import Field

from vsa_agent.agents.postprocessing.validators.base import BaseValidator

logger = logging.getLogger(__name__)


class PostprocessingResult(BaseModel):
    """Result from postprocessing. Mirrors NVIDIA PostprocessingResult."""

    passed: bool
    feedback: str = ""


class ValidationPipeline:
    """Runs validators in sequence, stopping on first failure."""

    def __init__(self, validators: list[BaseValidator] | None = None):
        self.validators = validators or []

    async def process(self, output: str) -> PostprocessingResult:
        """Run all validators on output. Stops on first failure."""
        for validator in self.validators:
            try:
                result = await validator.validate(output)
                if not result.passed:
                    feedback = f"[{validator.name}] FAILED: {validator.format_feedback(result.issues)}"
                    logger.info(feedback)
                    return PostprocessingResult(passed=False, feedback=feedback)
                logger.debug("%s: PASSED", validator.name)
            except Exception as e:
                logger.error("%s: error — %s", validator.name, e)
                return PostprocessingResult(passed=False, feedback=f"[{validator.name}] ERROR: {e}")
        return PostprocessingResult(passed=True)

