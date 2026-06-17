"""Parse VLM reasoning content (thinking/answer separation).

Handles structured reasoning output from models that support
chain-of-thought or thinking tags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReasoningResult:
    """Parsed reasoning result with separated thinking and answer."""
    thinking: str = ""
    answer: str = ""
    has_reasoning: bool = False


def parse_reasoning_content(content: str) -> ReasoningResult:
    """Parse VLM response to separate reasoning/thinking from final answer.

    Supports common formats:
    -  thinking...answer
    - <thinking>...</thinking>answer
    - <answer>...</answer>
    - Plain text (no reasoning)

    Args:
        content: Raw VLM response content.

    Returns:
        ReasoningResult with separated thinking and answer.
    """
    if not content:
        return ReasoningResult()

    # Try  thinking...response format first (used by some VLM providers)
    if content.startswith(" thinking"):
        rest = content[9:]  # skip " thinking"

        # Check for  response separator
        resp_idx = rest.find(" response")
        if resp_idx >= 0:
            after_response = rest[resp_idx + len(" response"):].strip()
            # Check for <answer> tag in the response part
            answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", after_response, re.DOTALL)
            if answer_match:
                return ReasoningResult(
                    thinking=rest[:resp_idx].strip(),
                    answer=answer_match.group(1).strip(),
                    has_reasoning=True,
                )
            return ReasoningResult(
                thinking=rest[:resp_idx].strip(),
                answer=after_response,
                has_reasoning=True,
            )

        # No  response separator - everything after  is thinking
        return ReasoningResult(
            thinking=rest.strip(),
            answer="",
            has_reasoning=True,
        )

    # Try <thinking> tags
    thinking_pattern = r"<thinking>(.*?)</thinking>\s*(.*)"
    match = re.search(thinking_pattern, content, re.DOTALL)
    if match:
        trailing_answer = match.group(2).strip()
        answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", trailing_answer, re.DOTALL)
        return ReasoningResult(
            thinking=match.group(1).strip(),
            answer=answer_match.group(1).strip() if answer_match else trailing_answer,
            has_reasoning=True,
        )

    # Try <answer> tags
    think_pattern = r"(.*?)\s*<answer>\s*(.*?)\s*</answer>"
    match = re.search(think_pattern, content, re.DOTALL)
    if match:
        return ReasoningResult(
            thinking=match.group(1).strip(),
            answer=match.group(2).strip(),
            has_reasoning=True,
        )

    # No structured reasoning found
    return ReasoningResult(answer=content.strip(), has_reasoning=False)


def parse_content_blocks(content: str | None) -> list[dict[str, str]]:
    if not content:
        return [{"type": "answer", "content": ""}]

    thinking_matches = re.findall(r"<thinking>\s*(.*?)\s*</thinking>", content, re.DOTALL)
    answer_matches = re.findall(r"<answer>\s*(.*?)\s*</answer>", content, re.DOTALL)
    if thinking_matches or answer_matches:
        blocks: list[dict[str, str]] = []
        for item in thinking_matches:
            blocks.append({"type": "thinking", "content": item.strip()})
        for item in answer_matches:
            blocks.append({"type": "answer", "content": item.strip()})
        return blocks or [{"type": "answer", "content": ""}]

    result = parse_reasoning_content(content)
    blocks: list[dict[str, str]] = []
    if result.thinking:
        blocks.append({"type": "thinking", "content": result.thinking})
    if result.answer:
        blocks.append({"type": "answer", "content": result.answer})
    if not blocks:
        return [{"type": "answer", "content": ""}]
    return blocks
