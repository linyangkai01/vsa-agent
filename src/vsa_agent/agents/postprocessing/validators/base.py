"""Base validator abstract class. Mirrors NVIDIA BaseValidator."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ValidatorResult(BaseModel):
    """Result from a validator. Mirrors NVIDIA ValidatorResult."""

    name: str
    passed: bool
    issues: list[str] = Field(default_factory=list)


class BaseValidator(ABC):
    """Abstract base for validators. Mirrors NVIDIA BaseValidator."""

    name: str = "base_validator"

    def __init__(self, feedback_template: str = ""):
        self.feedback_template = feedback_template

    @abstractmethod
    async def validate(self, output: str, **kwargs: Any) -> ValidatorResult:
        """Run validation on output. Must be implemented by subclasses."""
        pass

    def format_feedback(self, issues: list[str]) -> str:
        """Format feedback message from issues list."""
        if not issues:
            return ""
        issues_str = ", ".join(issues)
        if not self.feedback_template:
            return issues_str
        return self.feedback_template.replace("{issues}", issues_str)
