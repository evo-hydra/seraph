"""Tests for reporter module."""

from __future__ import annotations

import pytest

from verdict.core.reporter import (
    build_report,
    compute_baseline_score,
    compute_co_change_score,
    compute_mutation_score,
    compute_risk_score,
    compute_static_score,
    DIMENSION_WEIGHTS,
)
from verdict.models.assessment import (
    BaselineResult,
    HotFileInfo,
    MissingCoChange,
    MutationResult,
    PitfallMatch,
    SentinelSignals,
    StaticFinding,
)
from verdict.models.enums import Grade, MutantStatus, Severity


class TestComputeBaselineScore:
    def test_no_flaky(self):
        baseline = BaselineResult(flaky_tests=[], pass_rate=1.0)
        assert compute_baseline_score(baseline) == 100.0

    def test_with_flaky(self):
        baseline = BaselineResult(flaky_tests=["t1", "t2"], pass_rate=0.8)
        assert compute_baseline_score(baseline) == 80.0


class TestComputeMutationScore:
    def test_no_mutants(self):
        assert compute_mutation_score([]) == 100.0

    def test_half_killed(self):
        results = [
            MutationResult(status=MutantStatus.KILLED),
            MutationResult(status=MutantStatus.SURVIVED),
        ]
        assert compute_mutation_score(results) == 50.0


class TestComputeStaticScore:
    def test_no_findings(self):
        assert compute_static_score([], 5) == 100.0

    def test_zero_files(self):
        assert compute_static_score([], 0) == 100.0

    def test_with_findings(self):
        findings = [
            StaticFinding(severity=Severity.HIGH),
            StaticFinding(severity=Severity.LOW),
        ]
        # weighted: 5 + 1 = 6, per file = 6/2 = 3, score = 100 - 30 = 70
        assert compute_static_score(findings, 2) == 70.0


class TestComputeRiskScore:
    def test_no_data(self):
        signals = SentinelSignals(available=False)
        assert compute_risk_score(signals) == 100.0

    def test_with_signals(self):
        signals = SentinelSignals(
            available=True,
            pitfall_matches=[PitfallMatch(), PitfallMatch()],
            hot_files=[HotFileInfo(churn_score=50)],
            missing_co_changes=[MissingCoChange()],
        )
        # 2 pitfalls * 5 = 10, 1 hot file (50/5=10 capped at 10) = 10, 1 missing * 3 = 3
        assert compute_risk_score(signals) == 77.0


class TestComputeCoChangeScore:
    def test_no_data(self):
        signals = SentinelSignals(available=False)
        assert compute_co_change_score(signals, ["a.py"]) == 100.0

    def test_with_missing(self):
        signals = SentinelSignals(
            available=True,
            missing_co_changes=[MissingCoChange(), MissingCoChange()],
        )
        # 2 changed + 2 missing = 4 total partners, coverage = 2/4 = 50%
        assert compute_co_change_score(signals, ["a.py", "d.py"]) == 50.0


class TestBuildReport:
    def test_perfect_scores(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before=None,
            ref_after=None,
            files_changed=["foo.py"],
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
        assert report.overall_score == 100.0
        assert report.overall_grade == Grade.A
        assert report.gaps == []

    def test_mixed_scores(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before=None,
            ref_after=None,
            files_changed=["foo.py"],
            mutation_score=50.0,
            static_score=80.0,
            baseline_score=100.0,
            sentinel_risk_score=70.0,
            co_change_score=60.0,
            mutations=[MutationResult(status=MutantStatus.SURVIVED)],
            static_findings=[StaticFinding(severity=Severity.LOW)],
            baseline=None,
            sentinel_signals=SentinelSignals(),
        )
        # 50*0.3 + 80*0.2 + 100*0.15 + 70*0.2 + 60*0.15
        # = 15 + 16 + 15 + 14 + 9 = 69
        assert report.overall_score == 69.0
        assert report.overall_grade == Grade.C
        assert len(report.gaps) > 0

    def test_dimensions_count(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before=None,
            ref_after=None,
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
        assert len(report.dimensions) == 5

    def test_weights_sum_to_one(self):
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_to_dict(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before="abc",
            ref_after="def",
            files_changed=["a.py"],
            mutation_score=90.0,
            static_score=90.0,
            baseline_score=90.0,
            sentinel_risk_score=90.0,
            co_change_score=90.0,
            mutations=[],
            static_findings=[],
            baseline=None,
            sentinel_signals=SentinelSignals(),
        )
        d = report.to_dict()
        assert d["ref_before"] == "abc"
        assert d["ref_after"] == "def"
        assert d["overall_grade"] == "A"
        assert len(d["dimensions"]) == 5

    def test_f_grade_threshold(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before=None,
            ref_after=None,
            files_changed=["foo.py"],
            mutation_score=10.0,
            static_score=10.0,
            baseline_score=10.0,
            sentinel_risk_score=10.0,
            co_change_score=10.0,
            mutations=[],
            static_findings=[],
            baseline=None,
            sentinel_signals=SentinelSignals(),
        )
        assert report.overall_grade == Grade.F

    def test_evaluated_dimensions_subset(self):
        report = build_report(
            repo_path="/tmp/test",
            ref_before=None,
            ref_after=None,
            files_changed=["foo.py"],
            mutation_score=50.0,
            static_score=100.0,
            baseline_score=100.0,
            sentinel_risk_score=100.0,
            co_change_score=100.0,
            mutations=[],
            static_findings=[],
            baseline=None,
            sentinel_signals=SentinelSignals(),
            evaluated_dimensions={"mutation"},
        )
        # Only mutation is evaluated, so overall = mutation score
        assert report.overall_score == 50.0
        evaluated = [d for d in report.dimensions if d.evaluated]
        assert len(evaluated) == 1
        assert evaluated[0].name == "Mutation Score"
