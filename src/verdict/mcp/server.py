"""Verdict MCP server — FastMCP with stdio transport."""

from __future__ import annotations

import json
import os
from pathlib import Path

from verdict.core.engine import VerdictEngine
from verdict.core.store import VerdictStore
from verdict.mcp.formatters import (
    format_assessment,
    format_feedback_response,
    format_history,
    format_mutations,
)
from verdict.models.assessment import Feedback
from verdict.models.enums import FeedbackOutcome


def _get_repo_path() -> Path:
    """Determine repo path from env or cwd."""
    return Path(os.environ.get("VERDICT_REPO_PATH", os.getcwd())).resolve()


def _get_store(repo_path: Path) -> VerdictStore:
    """Create and open a VerdictStore for the repo."""
    db_path = repo_path / ".verdict" / "verdict.db"
    store = VerdictStore(db_path)
    store.open()
    return store


def create_server():
    """Create the Verdict MCP server."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "verdict",
        description="Verification intelligence for AI-generated code",
    )

    @mcp.tool()
    def verdict_assess(
        ref_before: str = "",
        ref_after: str = "",
        skip_baseline: bool = False,
        skip_mutations: bool = False,
    ) -> str:
        """Run full assessment pipeline on current diff or specified refs.

        Analyzes code changes through mutation testing, static analysis,
        and Sentinel project intelligence to produce a multi-metric grade.

        Args:
            ref_before: Git ref before changes (default: HEAD)
            ref_after: Git ref after changes (default: working tree)
            skip_baseline: Skip flakiness baseline (faster)
            skip_mutations: Skip mutation testing (much faster)
        """
        repo_path = _get_repo_path()
        store = _get_store(repo_path)
        try:
            engine = VerdictEngine(
                store,
                skip_baseline=skip_baseline,
                skip_mutations=skip_mutations,
            )
            report = engine.assess(
                repo_path,
                ref_before=ref_before or None,
                ref_after=ref_after or None,
            )
            return format_assessment(report.to_dict())
        finally:
            store.close()

    @mcp.tool()
    def verdict_mutate(
        ref_before: str = "",
        ref_after: str = "",
    ) -> str:
        """Run mutation testing only on changed files.

        A focused subset of the full assessment that only runs mutmut
        on files in the diff.

        Args:
            ref_before: Git ref before changes (default: HEAD)
            ref_after: Git ref after changes (default: working tree)
        """
        repo_path = _get_repo_path()
        store = _get_store(repo_path)
        try:
            engine = VerdictEngine(store)
            report = engine.mutate_only(
                repo_path,
                ref_before=ref_before or None,
                ref_after=ref_after or None,
            )
            return format_mutations(
                [{"file_path": m.file_path, "line_number": m.line_number,
                  "operator": m.operator, "status": m.status.value}
                 for m in report.mutations],
                report.mutation_score,
            )
        finally:
            store.close()

    @mcp.tool()
    def verdict_history(
        limit: int = 10,
        offset: int = 0,
    ) -> str:
        """Query past assessments with pagination.

        Args:
            limit: Maximum number of results (default 10)
            offset: Number of results to skip (default 0)
        """
        repo_path = _get_repo_path()
        store = _get_store(repo_path)
        try:
            assessments = store.get_assessments(limit=limit, offset=offset)
            return format_history(assessments)
        finally:
            store.close()

    @mcp.tool()
    def verdict_feedback(
        assessment_id: str,
        outcome: str,
        context: str = "",
    ) -> str:
        """Submit feedback on an assessment.

        Helps Verdict learn which assessments are useful.

        Args:
            assessment_id: The assessment ID to give feedback on
            outcome: One of: accepted, rejected, modified
            context: Optional explanation
        """
        repo_path = _get_repo_path()
        store = _get_store(repo_path)
        try:
            # Validate outcome
            try:
                fb_outcome = FeedbackOutcome(outcome)
            except ValueError:
                return f"Invalid outcome '{outcome}'. Must be: accepted, rejected, or modified"

            # Verify assessment exists
            assessment = store.get_assessment(assessment_id)
            if not assessment:
                return f"Assessment '{assessment_id}' not found"

            fb = Feedback(
                assessment_id=assessment_id,
                outcome=fb_outcome,
                context=context,
            )
            store.save_feedback(fb)
            return format_feedback_response(assessment_id, outcome)
        finally:
            store.close()

    return mcp


def main():
    """Entry point for verdict-mcp."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
