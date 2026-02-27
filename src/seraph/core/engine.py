"""SeraphEngine — 7-step assessment pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from seraph.config import SeraphConfig
from seraph.core.baseline import run_baseline
from seraph.core.bridge import SentinelBridge
from seraph.core.differ import parse_diff
from seraph.core.mutator import run_mutations
from seraph.core.reporter import (
    build_report,
    compute_baseline_score,
    compute_co_change_score,
    compute_mutation_score,
    compute_risk_score,
    compute_static_score,
)
from seraph.core.static import run_static_analysis
from seraph.core.store import SeraphStore
from seraph.models.assessment import (
    AssessmentReport,
    SentinelSignals,
)

logger = logging.getLogger(__name__)


class SeraphEngine:
    """Main assessment engine implementing the 7-step pipeline.

    Steps:
    1. Diff    — Parse git diff to get changed files + line ranges
    2. Baseline — Run test suite 3x unmutated, identify flaky tests
    3. Mutate  — Run mutmut scoped to changed files only
    4. Static  — Run ruff + mypy on changed files
    5. Sentinel — Query pitfalls, co-changes, hot files
    6. Report  — Generate multi-metric vector with grades
    7. Persist — Write assessment to SQLite
    """

    def __init__(
        self,
        store: SeraphStore,
        *,
        config: SeraphConfig | None = None,
        test_cmd: str = "pytest",
        baseline_runs: int | None = None,
        mutation_timeout: int | None = None,
        static_timeout: int | None = None,
        skip_baseline: bool = False,
        skip_mutations: bool = False,
    ):
        self._store = store
        self._config = config or SeraphConfig()
        self._test_cmd = test_cmd
        self._baseline_runs = baseline_runs or self._config.pipeline.baseline_runs
        self._mutation_timeout = mutation_timeout or self._config.timeouts.mutation_per_file
        self._static_timeout = static_timeout or self._config.timeouts.static_analysis
        self._skip_baseline = skip_baseline
        self._skip_mutations = skip_mutations

    def assess(
        self,
        repo_path: str | Path,
        ref_before: str | None = None,
        ref_after: str | None = None,
    ) -> AssessmentReport:
        """Run the full 7-step assessment pipeline."""
        repo = Path(repo_path).resolve()
        scoring = self._config.scoring

        # Step 1: Diff
        diff = parse_diff(repo, ref_before, ref_after)
        py_files = diff.python_files
        all_files = diff.file_paths

        if not all_files:
            report = self._empty_report(str(repo), ref_before, ref_after)
            self._store.save_assessment(report)
            return report

        # Track which dimensions are actually evaluated
        evaluated = {"static", "sentinel_risk", "co_change"}

        # Step 2: Baseline
        baseline = None
        baseline_score = 100.0
        if not self._skip_baseline and py_files:
            try:
                baseline = run_baseline(repo, self._test_cmd, self._baseline_runs)
                baseline_score = compute_baseline_score(baseline, scoring)
                evaluated.add("baseline")
            except Exception:
                logger.exception("Step 2 (Baseline) failed")

        # Step 3: Mutate
        mutations: list = []
        mutation_score = 100.0
        if not self._skip_mutations and py_files:
            try:
                mutations = run_mutations(repo, py_files, self._mutation_timeout)
                mutation_score = compute_mutation_score(mutations)
                evaluated.add("mutation")
            except Exception:
                logger.exception("Step 3 (Mutation) failed")

        # Step 4: Static analysis (only if Python files changed)
        static_findings: list = []
        static_score = 100.0
        if py_files:
            try:
                static_findings = run_static_analysis(repo, py_files, self._static_timeout)
                static_score = compute_static_score(static_findings, len(py_files), scoring)
            except Exception:
                logger.exception("Step 4 (Static Analysis) failed")

        # Step 5: Sentinel
        sentinel_signals = SentinelSignals()
        try:
            with SentinelBridge(repo) as bridge:
                sentinel_signals = bridge.get_risk_signals(all_files)
        except Exception:
            logger.exception("Step 5 (Sentinel) failed")

        sentinel_risk_score = compute_risk_score(sentinel_signals, scoring)
        co_change_score = compute_co_change_score(sentinel_signals, all_files)

        # Step 6: Report
        report = build_report(
            repo_path=str(repo),
            ref_before=ref_before,
            ref_after=ref_after,
            files_changed=all_files,
            mutation_score=mutation_score,
            static_score=static_score,
            baseline_score=baseline_score,
            sentinel_risk_score=sentinel_risk_score,
            co_change_score=co_change_score,
            mutations=mutations,
            static_findings=static_findings,
            baseline=baseline,
            sentinel_signals=sentinel_signals,
            evaluated_dimensions=evaluated,
            scoring=scoring,
        )

        # Step 7: Persist
        self._store.save_assessment(report)

        return report

    def mutate_only(
        self,
        repo_path: str | Path,
        ref_before: str | None = None,
        ref_after: str | None = None,
    ) -> AssessmentReport:
        """Run only mutation testing (subset of full assess).

        Only the mutation dimension is evaluated. Other dimensions are
        marked as not evaluated and excluded from the overall score.
        """
        repo = Path(repo_path).resolve()
        diff = parse_diff(repo, ref_before, ref_after)
        py_files = diff.python_files

        mutations = run_mutations(repo, py_files, self._mutation_timeout) if py_files else []
        mutation_score = compute_mutation_score(mutations)

        report = build_report(
            repo_path=str(repo),
            ref_before=ref_before,
            ref_after=ref_after,
            files_changed=diff.file_paths,
            mutation_score=mutation_score,
            static_score=100.0,
            baseline_score=100.0,
            sentinel_risk_score=100.0,
            co_change_score=100.0,
            mutations=mutations,
            static_findings=[],
            baseline=None,
            sentinel_signals=SentinelSignals(),
            evaluated_dimensions={"mutation"},
            scoring=self._config.scoring,
        )

        self._store.save_assessment(report)
        return report

    def _empty_report(
        self, repo_path: str, ref_before: str | None, ref_after: str | None
    ) -> AssessmentReport:
        """Return a report for no changes."""
        return build_report(
            repo_path=repo_path,
            ref_before=ref_before,
            ref_after=ref_after,
            files_changed=[],
            mutation_score=100.0,
            static_score=100.0,
            baseline_score=100.0,
            sentinel_risk_score=100.0,
            co_change_score=100.0,
            mutations=[],
            static_findings=[],
            baseline=None,
            sentinel_signals=SentinelSignals(),
            scoring=self._config.scoring,
        )
