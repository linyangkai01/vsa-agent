"""URL validation validator."""

import re
from typing import Any

from vsa_agent.agents.postprocess.validators.base import BaseValidator
from vsa_agent.agents.postprocess.validators.base import ValidatorResult


class URLValidator(BaseValidator):
    """Validates URLs in output are well-formed."""

    name = "url_validator"
    URL_PATTERN = re.compile(r"https?://[^\s]+")

    async def validate(self, output: str, **kwargs: Any) -> ValidatorResult:
        if not output or not output.strip():
            return ValidatorResult(name=self.name, passed=True)
        urls = self.URL_PATTERN.findall(output)
        invalid = [u for u in urls if not u.startswith(("http://", "https://"))]
        if invalid:
            return ValidatorResult(
                name=self.name, passed=False,
                issues=[f"Invalid URLs: {invalid}"],
            )
        return ValidatorResult(name=self.name, passed=True)
