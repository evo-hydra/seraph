"""Tests for VerdictStore."""

from __future__ import annotations

import json

import pytest

from verdict.core.store import VerdictStore
from verdict.models.assessment import (
    AssessmentReport,
    BaselineResult,
    Feedback,
    MutationResult,
)
from verdict.models.enums import FeedbackOutcome, Grade, MutantStatus


class TestVerdictStore:
    def test_open_creates_tables(self, store: VerdictStore):
        cur = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cur.fetchall()}
        assert "assessments" in tables
        assert "baselines" in tables
        assert "mutation_cache" in tables
        assert "feedback" in tables
        assert "verdict_meta" in tables

    def test_schema_version(self, store: VerdictStore):
        cur = store.conn.execute(
            "SELECT value FROM verdict_meta WHERE key = 'schema_version'"
        )
        assert cur.fetchone()["value"] == "1"

    def test_wal_mode(self, store: VerdictStore):
        cur = store.conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0] == "wal"

    def test_save_and_get_assessment(self, store: VerdictStore):
        report = AssessmentReport(
            repo_path="/tmp/test",
            files_changed=["foo.py", "bar.py"],
            overall_score=85.0,
            overall_grade=Grade.B,
            mutation_score=90.0,
            static_issues=2,
        )
        store.save_assessment(report)

        fetched = store.get_assessment(report.id)
        assert fetched is not None
        assert fetched.repo_path == "/tmp/test"
        assert fetched.grade == "B"
        assert fetched.mutation_score == 90.0
        assert fetched.files_changed == ["foo.py", "bar.py"]

    def test_get_assessments_pagination(self, store: VerdictStore):
        for i in range(5):
            report = AssessmentReport(
                repo_path="/tmp/test",
                files_changed=[f"file{i}.py"],
                overall_grade=Grade.A,
            )
            store.save_assessment(report)

        all_results = store.get_assessments(limit=10)
        assert len(all_results) == 5

        page = store.get_assessments(limit=2, offset=0)
        assert len(page) == 2

        page2 = store.get_assessments(limit=2, offset=2)
        assert len(page2) == 2

    def test_save_assessment_with_mutations(self, store: VerdictStore):
        mutations = [
            MutationResult(file_path="foo.py", mutant_id="1", operator="negate", status=MutantStatus.KILLED),
            MutationResult(file_path="foo.py", mutant_id="2", operator="remove", status=MutantStatus.SURVIVED),
        ]
        report = AssessmentReport(
            repo_path="/tmp/test",
            files_changed=["foo.py"],
            overall_grade=Grade.B,
            mutations=mutations,
        )
        store.save_assessment(report)

        saved_mutations = store.get_mutations(report.id)
        assert len(saved_mutations) == 2
        statuses = {m.status for m in saved_mutations}
        assert statuses == {"killed", "survived"}

    def test_save_assessment_with_baseline(self, store: VerdictStore):
        baseline = BaselineResult(
            repo_path="/tmp/test",
            flaky_tests=["test_a", "test_b"],
            pass_rate=0.95,
        )
        report = AssessmentReport(
            repo_path="/tmp/test",
            files_changed=["foo.py"],
            overall_grade=Grade.C,
            baseline=baseline,
        )
        store.save_assessment(report)

        saved_baseline = store.get_latest_baseline("/tmp/test")
        assert saved_baseline is not None
        assert saved_baseline.pass_rate == 0.95
        assert saved_baseline.flaky_tests == ["test_a", "test_b"]

    def test_save_and_get_feedback(self, store: VerdictStore):
        report = AssessmentReport(
            repo_path="/tmp/test",
            files_changed=["foo.py"],
            overall_grade=Grade.A,
        )
        store.save_assessment(report)

        fb = Feedback(
            assessment_id=report.id,
            outcome=FeedbackOutcome.ACCEPTED,
            context="Good assessment",
        )
        store.save_feedback(fb)

        feedbacks = store.get_feedback(report.id)
        assert len(feedbacks) == 1
        assert feedbacks[0].outcome == "accepted"
        assert feedbacks[0].context == "Good assessment"

    def test_stats(self, store: VerdictStore):
        stats = store.stats()
        assert stats["assessments"] == 0
        assert stats["feedback"] == 0

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "test.db"
        with VerdictStore(db_path) as s:
            s.conn.execute("SELECT 1")
        # Should be closed
        assert s._conn is None

    def test_get_nonexistent_assessment(self, store: VerdictStore):
        assert store.get_assessment("nonexistent") is None
