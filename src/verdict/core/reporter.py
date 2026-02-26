"""Multi-metric report generation with 5-dimension scoring."""

from __future__ import annotations

from verdict.models.assessment import (
    AssessmentReport,
    BaselineResult,
    DimensionScore,
    SentinelSignals,
    StaticFinding,
    MutationResult,
)
from verdict.models.enums import Grade

# ── Weight Configuration ──────────────────────────────────────

DIMENSION_WEIGHTS = {
    "mutation": 0.30,
    "static": 0.20,
    "baseline": 0.15,
    "sentinel_risk": 0.20,
    "co_change": 0.15,
}


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
) -> AssessmentReport:
    """Build a complete assessment report from individual dimension scores."""

    dimensions = [
        _score_dimension("Mutation Score", mutation_score, DIMENSION_WEIGHTS["mutation"],
                         _mutation_details(mutation_score, mutations)),
        _score_dimension("Static Cleanliness", static_score, DIMENSION_WEIGHTS["static"],
                         _static_details(static_findings)),
        _score_dimension("Test Baseline", baseline_score, DIMENSION_WEIGHTS["baseline"],
                         _baseline_details(baseline)),
        _score_dimension("Sentinel Risk", sentinel_risk_score, DIMENSION_WEIGHTS["sentinel_risk"],
                         _sentinel_details(sentinel_signals)),
        _score_dimension("Co-change Coverage", co_change_score, DIMENSION_WEIGHTS["co_change"],
                         _cochange_details(sentinel_signals)),
    ]

    overall_score = sum(d.weighted_score for d in dimensions)
    overall_grade = Grade.from_score(overall_score)
    gaps = _identify_gaps(dimensions)

    report = AssessmentReport(
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

    return report


def _score_dimension(
    name: str, raw_score: float, weight: float, details: str
) -> DimensionScore:
    return DimensionScore(
        name=name,
        raw_score=round(raw_score, 1),
        weight=weight,
        weighted_score=round(raw_score * weight, 1),
        grade=Grade.from_score(raw_score),
        details=details,
    )


def _identify_gaps(dimensions: list[DimensionScore]) -> list[str]:
    """Identify dimensions that need attention (grade C or below)."""
    gaps: list[str] = []
    for d in dimensions:
        if d.grade in (Grade.C, Grade.D, Grade.F):
            gaps.append(f"{d.name}: {d.grade.value} ({d.raw_score}%) — {d.details}")
    return gaps


# ── Detail Formatters ─────────────────────────────────────────

def _mutation_details(score: float, mutations: list[MutationResult]) -> str:
    if not mutations:
        return "No mutants generated"
    total = len(mutations)
    killed = sum(1 for m in mutations if m.status.value == "killed")
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
    files = [m.get("partner_file", "?") if isinstance(m, dict) else "?" for m in missing[:3]]
    suffix = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
    return f"Missing: {', '.join(files)}{suffix}"
