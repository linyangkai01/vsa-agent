"""Summary layer for dual-track video understanding output."""

from langchain_core.messages import HumanMessage, SystemMessage

from vsa_agent.data_models.understanding import DetectedEvent, SummaryResult, UnderstandingResult
from vsa_agent.registry import register_tool
from vsa_agent.video_analytics.nvschema import Incident


def _parse_hhmmss(value: str) -> int | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _merge_summary_events(events: list[DetectedEvent]) -> list[DetectedEvent]:
    if not events:
        return []

    def _sort_key(event: DetectedEvent) -> int:
        return _parse_hhmmss(event.start_timestamp) or 0

    sorted_events = sorted(events, key=_sort_key)
    merged: list[DetectedEvent] = [sorted_events[0]]

    for current in sorted_events[1:]:
        previous = merged[-1]
        prev_end = _parse_hhmmss(previous.end_timestamp)
        cur_start = _parse_hhmmss(current.start_timestamp)
        can_merge = (
            previous.label == current.label
            and previous.description == current.description
            and prev_end is not None
            and cur_start is not None
            and cur_start <= prev_end
        )
        if can_merge:
            merged[-1] = previous.model_copy(
                update={
                    "end_timestamp": current.end_timestamp,
                    "evidence": [*previous.evidence, *current.evidence],
                }
            )
        else:
            merged.append(current)

    return merged


def _events_to_text(events: list[DetectedEvent]) -> str:
    merged_events = _merge_summary_events(events)
    lines = []
    for event in merged_events:
        if event.start_timestamp or event.end_timestamp:
            lines.append(f"[{event.start_timestamp} - {event.end_timestamp}] {event.description}")
        else:
            lines.append(event.description)
    return "\n".join(line for line in lines if line)


def _incident_time_window(incident: Incident) -> tuple[str, str]:
    metadata = incident.metadata or {}
    start_time = str(metadata.get("start_time", "") or "")
    end_time = str(metadata.get("end_time", "") or "")
    return start_time, end_time


def _risk_digest_to_text(result: UnderstandingResult) -> str:
    digest = result.metadata.get("risk_digest")
    if not isinstance(digest, list) or not digest:
        return ""

    lines = [
        "Risk digest by chunk:",
        "Use the evidence type carefully: state observed evidence as fact, "
        "and label inferred_or_recommended items as checks or recommendations. "
        "Only state direct observations as facts.",
    ]
    for item in digest:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "") or "Additional evidence")
        chunk_index = item.get("chunk_index")
        time_range = item.get("time_range") if isinstance(item.get("time_range"), dict) else {}
        start = str(time_range.get("start") or item.get("start_timestamp", "") or "")
        end = str(time_range.get("end") or item.get("end_timestamp", "") or "")
        evidence = str(item.get("evidence", "") or "").strip()
        evidence_type = str(item.get("evidence_type", "") or "").strip()
        prefix = f"Chunk {chunk_index}" if chunk_index is not None else "Chunk"
        window = f" [{start} - {end}]" if start or end else ""
        evidence_marker = f" [{evidence_type}]" if evidence_type else ""
        if evidence:
            lines.append(f"- {prefix}{window} {category}{evidence_marker}: {evidence}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def summarize_search_incidents(incidents: list[Incident], query: str) -> str:
    del query
    if not incidents:
        return "No matching videos found."

    lines: list[str] = []
    for incident in incidents:
        start_time, end_time = _incident_time_window(incident)
        if start_time or end_time:
            lines.append(f"[{start_time} - {end_time}] {incident.description}")
        else:
            lines.append(incident.description)
    return "\n".join(lines)


@register_tool(
    "vss_summarize",
    description="Summarize structured understanding results into dual-track output.",
)
async def summarize_understanding_result(
    result: UnderstandingResult,
    query: str,
    model_adapter=None,
) -> SummaryResult:
    """Generate dual-track output from a structured understanding result."""
    if model_adapter is not None:
        prompt_body = (
            _risk_digest_to_text(result)
            or result.summary_text
            or _events_to_text(result.events)
            or "No notable events detected."
        )
        response = await model_adapter.invoke(
            [
                SystemMessage(content="You summarize structured video understanding results into concise plain text."),
                HumanMessage(
                    content=(
                        f"User query: {query}\n\n"
                        f"Structured summary:\n{prompt_body}\n\n"
                        "Write a concise natural-language answer."
                    )
                ),
            ]
        )
        text_output = str(response.content).strip() if response.content is not None else ""
        if not text_output:
            text_output = prompt_body
    else:
        risk_digest_text = _risk_digest_to_text(result)
        if risk_digest_text:
            text_output = risk_digest_text
        elif result.summary_text:
            text_output = result.summary_text
        elif result.events:
            text_output = _events_to_text(result.events)
            if not text_output:
                text_output = "No notable events detected."
        else:
            text_output = "No notable events detected."
    return SummaryResult(
        query=query,
        text_output=text_output,
        structured_output=result,
    )
