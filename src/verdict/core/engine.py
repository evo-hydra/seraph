"""VerdictEngine — 7-step assessment pipeline."""

from __future__ import annotations

from pathlib import Path

from verdict.core.baseline import run_baseline
from verdict.core.bridge import SentinelBridge
from verdict.core.differ import DiffResult, parse_diff
from verdict.core.mutator import compute_mutation_score, run_mutations
from verdict.core.reporter import build_report
from verdict.core.static import compute_static_score, run_static_analysis
from verdict.core.store import VerdictStore
from verdict.models.assessment import (
    AssessmentReport,
    BaselineResult,
    SentinelSignals,
)


class VerdictEngine:
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
        store: VerdictStore,
        *,
        test_cmd: str = "pytest",
        baseline_runs: int = 3,
        mutation_timeout: int = 120,
        static_timeout: int = 60,
        skip_baseline: bool = False,
        skip_mutations: bool = False,
    ):
        self._store = store
        self._test_cmd = test_cmd
        self._baseline_runs = baseline_runs
        self._mutation_timeout = mutation_timeout
        self._static_timeout = static_timeout
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

        # Step 1: Diff
        diff = parse_diff(repo, ref_before, ref_after)
        py_files = diff.python_files
        all_files = diff.file_paths

        if not all_files:
            return self._empty_report(str(repo), ref_before, ref_after)

        # Step 2: Baseline
        baseline: BaselineResult | None = None
        baseline_score = 100.0
        if not self._skip_baseline and py_files:
            baseline = run_baseline(repo, self._test_cmd, self._baseline_runs)
            baseline_score = self._compute_baseline_score(baseline)

        # Step 3: Mutate
        mutations = []
        mutation_score = 100.0
        if not self._skip_mutations and py_files:
            mutations = run_mutations(repo, py_files, self._mutation_timeout)
            mutation_score = compute_mutation_score(mutations)

        # Step 4: Static analysis
        static_findings = run_static_analysis(repo, py_files, self._static_timeout)
        static_score = compute_static_score(static_findings, max(len(py_files), 1))

        # Step 5: Sentinel
        bridge = SentinelBridge(repo)
        try:
            signals_dict = bridge.get_risk_signals(all_files)
            sentinel_risk_score = bridge.compute_risk_score(signals_dict)
            co_change_score = bridge.compute_co_change_score(signals_dict, all_files)

            sentinel_signals = SentinelSignals(
                available=signals_dict.get("available", False),
                pitfall_matches=signals_dict.get("pitfall_matches", []),
                hot_files=signals_dict.get("hot_files", []),
                missing_co_changes=signals_dict.get("missing_co_changes", []),
            )
        finally:
            bridge.close()

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
        """Run only mutation testing (subset of full assess)."""
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
        )

        self._store.save_assessment(report)
        return report

    def _compute_baseline_score(self, baseline: BaselineResult) -> float:
        """Convert baseline result to a 0-100 score."""
        flaky_count = len(baseline.flaky_tests)
        if flaky_count == 0:
            return 100.0
        # Each flaky test deducts 10 points, floor at 0
        return max(0.0, 100.0 - flaky_count * 10)

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
        )
