"""Multi-metric report generation with 5-dimension scoring.

All scoring logic is consolidated here — baseline, mutation, static,
sentinel risk, and co-change coverage scores are all computed in this module.
"""

from __future__ import annotations

from verdict.models.assessment import (
    AssessmentReport,
    BaselineResult,
    DimensionScore,
    HotFileInfo,
    MissingCoChange,
    MutationResult,
    PitfallMatch,
    SentinelSignals,
    StaticFinding,
)
from verdict.models.enums import Grade, MutantStatus, Severity

# ── Weight Configuration ──────────────────────────────────────

DIMENSION_WEIGHTS = {
    "mutation": 0.30,
    "static": 0.20,
    "baseline": 0.15,
    "sentinel_risk": 0.20,
    "co_change": 0.15,
}

# ── Scoring Constants ─────────────────────────────────────────

BASELINE_DEDUCTION_PER_FLAKY = 10.0
RISK_DEDUCTION_PER_PITFALL = 5.0
RISK_DEDUCTION_PER_MISSING_CO_CHANGE = 3.0
RISK_HOT_FILE_CHURN_DIVISOR = 5.0
RISK_HOT_FILE_MAX_DEDUCTION = 10.0
STATIC_ISSUE_SCALE_FACTOR = 10.0

SEVERITY_WEIGHTS = {
    Severity.CRITICAL: 10,
    Severity.HIGH: 5,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


# ── Score Computation Functions ───────────────────────────────


def compute_baseline_score(baseline: BaselineResult) -> float:
    """Convert baseline result to a 0-100 score."""
    flaky_count = len(baseline.flaky_tests)
    if flaky_count == 0:
        return 100.0
    return max(0.0, 100.0 - flaky_count * BASELINE_DEDUCTION_PER_FLAKY)


def compute_mutation_score(results: list[MutationResult]) -> float:
    """Compute mutation score as percentage of killed mutants."""
    if not results:
        return 100.0
    total = len(results)
    killed = sum(1 for r in results if r.status == MutantStatus.KILLED)
    return round((killed / total) * 100, 1)


def compute_static_score(findings: list[StaticFinding], file_count: int) -> float:
    """Compute static cleanliness score (0-100).

    Score decreases based on issues per file, weighted by severity.
    """
    if file_count == 0:
        return 100.0

    weighted_issues = sum(SEVERITY_WEIGHTS.get(f.severity, 1) for f in findings)
    issues_per_file = weighted_issues / file_count

    score = max(0.0, 100.0 - (issues_per_file * STATIC_ISSUE_SCALE_FACTOR))
    return round(score, 1)


def compute_risk_score(signals: SentinelSignals) -> float:
    """Compute Sentinel risk score (0-100, higher = safer)."""
    if not signals.available:
        return 100.0

    deductions = 0.0
    for hf in signals.hot_files:
        deductions += min(RISK_HOT_FILE_MAX_DEDUCTION, hf.churn_score / RISK_HOT_FILE_CHURN_DIVISOR)

    deductions += len(signals.pitfall_matches) * RISK_DEDUCTION_PER_PITFALL
    deductions += len(signals.missing_co_changes) * RISK_DEDUCTION_PER_MISSING_CO_CHANGE

    return round(max(0.0, 100.0 - deductions), 1)


def compute_co_change_score(signals: SentinelSignals, changed_files: list[str]) -> float:
    """Compute co-change coverage score (0-100).

    Measures whether all expected co-change partners are included in the diff.
    """
    if not signals.available:
        return 100.0

    missing = len(signals.missing_co_changes)
    if not missing and not changed_files:
        return 100.0

    total_partners = len(changed_files) + missing
    if total_partners == 0:
        return 100.0

    coverage = len(changed_files) / total_partners
    return round(coverage * 100, 1)


# ── Report Builder ────────────────────────────────────────────


def build_report(
    *,
    repo_path: str,
    ref_before: str | None,
    ref_after: str | None,
    files_changed: list[str],
    mutation_score: float,
    static_score: float,
    baseline_score: float,
    sentinel_risk_score: float,
    co_change_score: float,
    mutations: list[MutationResult],
    static_findings: list[StaticFinding],
    baseline: BaselineResult | None,
    sentinel_signals: SentinelSignals,
    evaluated_dimensions: set[str] | None = None,
) -> AssessmentReport:
    """Build a complete assessment report from individual dimension scores.

    Args:
        evaluated_dimensions: Set of dimension keys that were actually evaluated.
            If None, all dimensions are considered evaluated.
            Valid keys: "mutation", "static", "baseline", "sentinel_risk", "co_change"
    """
    all_dims = {"mutation", "static", "baseline", "sentinel_risk", "co_change"}
    evaluated = evaluated_dimensions if evaluated_dimensions is not None else all_dims

    dimensions = [
        _score_dimension("Mutation Score", mutation_score, DIMENSION_WEIGHTS["mutation"],
                         _mutation_details(mutations), "mutation" in evaluated),
        _score_dimension("Static Cleanliness", static_score, DIMENSION_WEIGHTS["static"],
                         _static_details(static_findings), "static" in evaluated),
        _score_dimension("Test Baseline", baseline_score, DIMENSION_WEIGHTS["baseline"],
                         _baseline_details(baseline), "baseline" in evaluated),
        _score_dimension("Sentinel Risk", sentinel_risk_score, DIMENSION_WEIGHTS["sentinel_risk"],
                         _sentinel_details(sentinel_signals), "sentinel_risk" in evaluated),
        _score_dimension("Co-change Coverage", co_change_score, DIMENSION_WEIGHTS["co_change"],
                         _cochange_details(sentinel_signals), "co_change" in evaluated),
    ]

    # Overall score only considers evaluated dimensions, re-weighted
    evaluated_dims = [d for d in dimensions if d.evaluated]
    if evaluated_dims:
        total_weight = sum(d.weight for d in evaluated_dims)
        if total_weight > 0:
            overall_score = sum(d.raw_score * (d.weight / total_weight) for d in evaluated_dims)
        else:
            overall_score = 100.0
    else:
        overall_score = 100.0

    overall_grade = Grade.from_score(overall_score)
    gaps = _identify_gaps(dimensions)

    return AssessmentReport(
        repo_path=repo_path,
        ref_before=ref_before,
        ref_after=ref_after,
        files_changed=files_changed,
        dimensions=dimensions,
        overall_score=round(overall_score, 1),
        overall_grade=overall_grade,
        mutation_score=mutation_score,
        static_issues=len(static_findings),
        sentinel_warnings=len(sentinel_signals.pitfall_matches) + len(sentinel_signals.hot_files),
        baseline_flaky=len(baseline.flaky_tests) if baseline else 0,
        gaps=gaps,
        mutations=mutations,
        static_findings=static_findings,
        baseline=baseline,
        sentinel_signals=sentinel_signals,
    )


def _score_dimension(
    name: str, raw_score: float, weight: float, details: str, evaluated: bool
) -> DimensionScore:
    if not evaluated:
        return DimensionScore(
            name=name,
            raw_score=raw_score,
            weight=weight,
            weighted_score=0.0,
            grade=Grade.from_score(raw_score),
            details="Not evaluated",
            evaluated=False,
        )
    return DimensionScore(
        name=name,
        raw_score=round(raw_score, 1),
        weight=weight,
        weighted_score=round(raw_score * weight, 1),
        grade=Grade.from_score(raw_score),
        details=details,
        evaluated=True,
    )


def _identify_gaps(dimensions: list[DimensionScore]) -> list[str]:
    """Identify dimensions that need attention (grade C or below)."""
    gaps: list[str] = []
    for d in dimensions:
        if not d.evaluated:
            continue
        if d.grade in (Grade.C, Grade.D, Grade.F):
            gaps.append(f"{d.name}: {d.grade.value} ({d.raw_score}%) — {d.details}")
    return gaps


# ── Detail Formatters ─────────────────────────────────────────

def _mutation_details(mutations: list[MutationResult]) -> str:
    if not mutations:
        return "No mutants generated"
    total = len(mutations)
    killed = sum(1 for m in mutations if m.status == MutantStatus.KILLED)
    survived = total - killed
    return f"{killed}/{total} killed, {survived} survived"


def _static_details(findings: list[StaticFinding]) -> str:
    if not findings:
        return "No issues found"
    by_analyzer: dict[str, int] = {}
    for f in findings:
        by_analyzer[f.analyzer.value] = by_analyzer.get(f.analyzer.value, 0) + 1
    parts = [f"{v} {k}" for k, v in sorted(by_analyzer.items())]
    return ", ".join(parts)


def _baseline_details(baseline: BaselineResult | None) -> str:
    if not baseline:
        return "Baseline not run"
    flaky = len(baseline.flaky_tests)
    if flaky == 0:
        return f"All stable across {baseline.run_count} runs"
    return f"{flaky} flaky test(s) detected across {baseline.run_count} runs"


def _sentinel_details(signals: SentinelSignals) -> str:
    if not signals.available:
        return "Sentinel data not available"
    parts: list[str] = []
    if signals.pitfall_matches:
        parts.append(f"{len(signals.pitfall_matches)} pitfall match(es)")
    if signals.hot_files:
        parts.append(f"{len(signals.hot_files)} hot file(s)")
    if not parts:
        return "No risk signals"
    return ", ".join(parts)


def _cochange_details(signals: SentinelSignals) -> str:
    if not signals.available:
        return "Sentinel data not available"
    missing = signals.missing_co_changes
    if not missing:
        return "All co-change partners included"
    files = [m.partner_file for m in missing[:3]]
    suffix = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
    return f"Missing: {', '.join(files)}{suffix}"
