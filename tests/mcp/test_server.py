"""Tests for MCP server."""

from __future__ import annotations

from verdict.mcp.formatters import (
    format_assessment,
    format_feedback_response,
    format_history,
    format_mutations,
)
from verdict.models.assessment import StoredAssessment


class TestFormatAssessment:
    def test_basic_format(self):
        report = {
            "id": "abc12345",
            "overall_grade": "B",
            "overall_score": 78.5,
            "files_changed": ["foo.py", "bar.py"],
            "dimensions": [
                {"name": "Mutation Score", "grade": "A", "raw_score": 95.0, "details": "10/10 killed"},
            ],
            "gaps": ["Static: C (55%) — 3 ruff issues"],
            "created_at": "2026-01-01 00:00:00",
        }
        output = format_assessment(report)
        assert "## Verdict Assessment: B" in output
        assert "78.5/100" in output
        assert "Mutation Score" in output
        assert "abc12345" in output

    def test_empty_report(self):
        output = format_assessment({"overall_grade": "?", "overall_score": 0})
        assert "## Verdict Assessment" in output


class TestFormatHistory:
    def test_empty(self):
        assert format_history([]) == "No assessments found."

    def test_with_entries(self):
        entries = [
            StoredAssessment(
                id="abc12345",
                grade="A",
                mutation_score=95.0,
                static_issues=0,
                files_changed=["foo.py"],
                created_at="2026-01-01",
            )
        ]
        output = format_history(entries)
        assert "abc12345" in output
        assert "A" in output


class TestFormatMutations:
    def test_no_mutations(self):
        output = format_mutations([], 100.0)
        assert "100%" in output

    def test_with_mutations(self):
        from verdict.models.assessment import MutationResult
        from verdict.models.enums import MutantStatus
        muts = [
            MutationResult(file_path="foo.py", line_number=5, operator="negate", status=MutantStatus.SURVIVED),
            MutationResult(file_path="foo.py", line_number=10, operator="remove", status=MutantStatus.KILLED),
        ]
        output = format_mutations(muts, 50.0)
        assert "50.0%" in output
        assert "Survived" in output or "survived" in output.lower()


class TestFormatFeedback:
    def test_format(self):
        output = format_feedback_response("abc12345678", "accepted")
        assert "accepted" in output
        assert "abc12345" in output
