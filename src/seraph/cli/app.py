"""Seraph CLI — Typer-based command interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from seraph.config import SeraphConfig
from seraph.core.engine import SeraphEngine
from seraph.core.store import SeraphStore
from seraph.models.assessment import AssessmentReport, Feedback
from seraph.models.enums import FeedbackOutcome

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="seraph",
    help="Verification intelligence for AI-generated code.",
    no_args_is_help=True,
)
console = Console()

# Global state set by the callback
_verbose: bool = False


@app.callback()
def main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Seraph — verification intelligence for AI-generated code."""
    global _verbose
    _verbose = verbose


def _get_store(repo_path: Path, config: SeraphConfig | None = None) -> SeraphStore:
    if config:
        db_path = repo_path / config.pipeline.db_dir / config.pipeline.db_name
    else:
        db_path = repo_path / ".seraph" / "seraph.db"
    return SeraphStore(db_path)


@app.command()
def assess(
    repo_path: Path = typer.Argument(Path("."), help="Path to the repository"),
    ref_before: Optional[str] = typer.Option(None, "--ref-before", "-b", help="Git ref before changes"),
    ref_after: Optional[str] = typer.Option(None, "--ref-after", "-a", help="Git ref after changes"),
    test_cmd: str = typer.Option("pytest", "--test-cmd", "-t", help="Test command"),
    skip_baseline: bool = typer.Option(False, "--skip-baseline", help="Skip flakiness baseline"),
    skip_mutations: bool = typer.Option(False, "--skip-mutations", help="Skip mutation testing"),
    output_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run a full assessment on code changes."""
    repo_path = repo_path.resolve()
    config = SeraphConfig.load(repo_path)

    # Setup logging after config is loaded
    from seraph.logging_setup import setup_logging
    setup_logging(config.logging, verbose=_verbose)

    try:
        with _get_store(repo_path, config) as store:
            engine = SeraphEngine(
                store,
                config=config,
                test_cmd=test_cmd,
                skip_baseline=skip_baseline,
                skip_mutations=skip_mutations,
            )

            with console.status("Running assessment..."):
                report = engine.assess(repo_path, ref_before, ref_after)

            if output_json:
                console.print_json(report.to_json())
                return

            _display_report(report)
    except typer.Exit:
        raise
    except Exception as exc:
        logger.debug("Assessment failed", exc_info=True)
        console.print(f"[red]Assessment failed: {exc}[/red]")
        if not _verbose:
            console.print("[dim]Run with --verbose for full traceback[/dim]")
        raise typer.Exit(1)


@app.command()
def history(
    repo_path: Path = typer.Argument(Path("."), help="Path to the repository"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", "-o", help="Results to skip"),
) -> None:
    """Show past assessment history."""
    repo_path = repo_path.resolve()

    with _get_store(repo_path) as store:
        assessments = store.get_assessments(limit=limit, offset=offset)
        if not assessments:
            console.print("[dim]No assessments found.[/dim]")
            return

        table = Table(title="Assessment History")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Grade", justify="center")
        table.add_column("Mutation", justify="right")
        table.add_column("Static", justify="right")
        table.add_column("Files", justify="right")
        table.add_column("Created")

        for a in assessments:
            file_count = len(a.files_changed) if a.files_changed else 0
            grade = a.grade or "?"
            grade_style = _grade_color(grade)
            mutation_display = f"{a.mutation_score}%" if a.mutation_score is not None else "?%"
            static_display = str(a.static_issues) if a.static_issues is not None else "?"
            table.add_row(
                a.id[:8],
                f"[{grade_style}]{grade}[/{grade_style}]",
                mutation_display,
                static_display,
                str(file_count),
                a.created_at or "?",
            )

        console.print(table)


@app.command()
def feedback(
    assessment_id: str = typer.Argument(help="Assessment ID"),
    outcome: str = typer.Argument(help="Outcome: accepted, rejected, or modified"),
    context: str = typer.Option("", "--context", "-c", help="Optional explanation"),
    repo_path: Path = typer.Option(Path("."), "--repo", "-r", help="Repository path"),
) -> None:
    """Submit feedback on an assessment."""
    repo_path = repo_path.resolve()

    try:
        fb_outcome = FeedbackOutcome(outcome)
    except ValueError:
        console.print(f"[red]Invalid outcome '{outcome}'. Must be: accepted, rejected, or modified[/red]")
        raise typer.Exit(1)

    with _get_store(repo_path) as store:
        assessment = store.get_assessment(assessment_id)
        if not assessment:
            console.print(f"[red]Assessment '{assessment_id}' not found[/red]")
            raise typer.Exit(1)

        fb = Feedback(
            assessment_id=assessment_id,
            outcome=fb_outcome,
            context=context,
        )
        store.save_feedback(fb)
        console.print(f"[green]Feedback recorded: {outcome} for {assessment_id[:8]}[/green]")


@app.command()
def prune(
    repo_path: Path = typer.Argument(Path("."), help="Path to the repository"),
    days: Optional[int] = typer.Option(None, "--days", "-d", help="Retention days (default from config)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete old assessment data beyond the retention period."""
    repo_path = repo_path.resolve()
    config = SeraphConfig.load(repo_path)
    retention_days = days if days is not None else config.retention.retention_days

    if not yes:
        confirm = typer.confirm(f"Delete data older than {retention_days} days?")
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            return

    with _get_store(repo_path, config) as store:
        result = store.prune(retention_days)
        total = sum(result.values())
        if total == 0:
            console.print("[dim]No data to prune.[/dim]")
        else:
            console.print(f"[green]Pruned {total} rows:[/green]")
            for table_name, count in result.items():
                if count > 0:
                    console.print(f"  {table_name}: {count}")


def _display_report(report: AssessmentReport) -> None:
    """Display a rich-formatted assessment report."""
    grade_style = _grade_color(report.overall_grade.value)

    # Header
    console.print(Panel(
        f"[bold {grade_style}]{report.overall_grade.value}[/bold {grade_style}] "
        f"({report.overall_score}/100) | "
        f"{len(report.files_changed)} files changed",
        title="Seraph Assessment",
    ))

    # Dimensions table
    table = Table(title="Dimensions")
    table.add_column("Dimension")
    table.add_column("Grade", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Weight", justify="right")
    table.add_column("Details")

    for d in report.dimensions:
        if d.evaluated:
            style = _grade_color(d.grade.value)
            table.add_row(
                d.name,
                f"[{style}]{d.grade.value}[/{style}]",
                f"{d.raw_score}%",
                f"{int(d.weight * 100)}%",
                d.details,
            )
        else:
            table.add_row(d.name, "[dim]N/A[/dim]", "—", f"{int(d.weight * 100)}%", "[dim]Not evaluated[/dim]")

    console.print(table)

    # Gaps
    if report.gaps:
        console.print("\n[bold yellow]Gaps (Need Attention):[/bold yellow]")
        for gap in report.gaps:
            console.print(f"  - {gap}")

    console.print(f"\n[dim]ID: {report.id}[/dim]")


def _grade_color(grade: str) -> str:
    return {
        "A": "green",
        "B": "blue",
        "C": "yellow",
        "D": "red",
        "F": "bold red",
    }.get(grade, "white")


if __name__ == "__main__":
    app()
