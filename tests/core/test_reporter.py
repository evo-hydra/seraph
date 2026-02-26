"""Tests for reporter module."""

from __future__ import annotations

import pytest

from verdict.core.reporter import build_report, DIMENSION_WEIGHTS
from verdict.models.assessment import (
    BaselineResult,
    MutationResult,
    SentinelSignals,
    StaticFinding,
)
from verdict.models.enums import Grade, MutantStatus, Severity


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
