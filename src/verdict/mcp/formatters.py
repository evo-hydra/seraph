"""LLM-friendly output formatting with 4K token cap."""

from __future__ import annotations

from typing import Any

# Approximate 4K tokens ≈ 16K chars
MAX_OUTPUT_CHARS = 16_000


def format_assessment(report_dict: dict) -> str:
    """Format an assessment report for LLM consumption."""
    lines: list[str] = []

    lines.append(f"## Verdict Assessment: {report_dict.get('overall_grade', '?')}")
    lines.append(f"Score: {report_dict.get('overall_score', 0)}/100")
    lines.append(f"Files: {len(report_dict.get('files_changed', []))}")
    lines.append("")

    # Dimensions
    lines.append("### Dimensions")
    for dim in report_dict.get("dimensions", []):
        lines.append(
            f"- **{dim['name']}**: {dim['grade']} ({dim['raw_score']}%) — {dim['details']}"
        )
    lines.append("")

    # Gaps
    gaps = report_dict.get("gaps", [])
    if gaps:
        lines.append("### Gaps (Need Attention)")
        for gap in gaps:
            lines.append(f"- {gap}")
        lines.append("")

    # Files
    files = report_dict.get("files_changed", [])
    if files:
        lines.append("### Changed Files")
        for f in files[:20]:
            lines.append(f"- {f}")
        if len(files) > 20:
            lines.append(f"- ... and {len(files) - 20} more")
        lines.append("")

    lines.append(f"ID: {report_dict.get('id', '?')}")
    lines.append(f"Created: {report_dict.get('created_at', '?')}")

    return _truncate("\n".join(lines))


def format_history(assessments: list) -> str:
    """Format assessment history for LLM consumption.

    Accepts list of StoredAssessment dataclasses.
    """
    if not assessments:
        return "No assessments found."

    lines: list[str] = []
    lines.append(f"## Assessment History ({len(assessments)} results)")
    lines.append("")

    for a in assessments:
        file_count = len(a.files_changed) if a.files_changed else 0
        lines.append(
            f"- **{a.grade or '?'}** | "
            f"mutation={a.mutation_score or '?'}% | "
            f"static={a.static_issues or '?'} issues | "
            f"{file_count} files | "
            f"{a.created_at or '?'} | "
            f"id={a.id[:8] if a.id else '?'}"
        )

    return _truncate("\n".join(lines))


def format_mutations(mutations: list[dict], score: float) -> str:
    """Format mutation results for LLM consumption."""
    if not mutations:
        return "No mutation results. Score: 100%"

    lines: list[str] = []
    lines.append(f"## Mutation Testing Results")
    lines.append(f"Score: {score}%")
    lines.append(f"Total mutants: {len(mutations)}")
    lines.append("")

    # Group by status
    by_status: dict[str, list[dict]] = {}
    for m in mutations:
        status = m.get("status", "unknown")
        by_status.setdefault(status, []).append(m)

    for status, muts in sorted(by_status.items()):
        lines.append(f"### {status.title()} ({len(muts)})")
        for m in muts[:10]:
            lines.append(f"- {m.get('file_path', '?')}:{m.get('line_number', '?')} [{m.get('operator', '?')}]")
        if len(muts) > 10:
            lines.append(f"- ... and {len(muts) - 10} more")
        lines.append("")

    return _truncate("\n".join(lines))


def format_feedback_response(assessment_id: str, outcome: str) -> str:
    """Format feedback confirmation."""
    return f"Feedback recorded: {outcome} for assessment {assessment_id[:8]}"


def _truncate(text: str) -> str:
    """Truncate to stay within 4K token budget."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[: MAX_OUTPUT_CHARS - 50] + "\n\n... (output truncated)"
