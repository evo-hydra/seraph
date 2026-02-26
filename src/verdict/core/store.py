"""SQLite storage for Verdict assessments and results."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from verdict.models.assessment import (
    AssessmentReport,
    BaselineResult,
    Feedback,
    MutationResult,
    StoredAssessment,
    StoredBaseline,
    StoredFeedback,
    StoredMutation,
)
from verdict.models.enums import FeedbackOutcome, Grade, MutantStatus

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS verdict_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    id              TEXT PRIMARY KEY,
    repo_path       TEXT NOT NULL,
    ref_before      TEXT,
    ref_after       TEXT,
    files_changed   TEXT NOT NULL,
    mutation_score  REAL,
    static_issues   INTEGER,
    sentinel_warnings INTEGER,
    baseline_flaky  INTEGER DEFAULT 0,
    grade           TEXT NOT NULL,
    report_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS baselines (
    id          TEXT PRIMARY KEY,
    repo_path   TEXT NOT NULL,
    test_cmd    TEXT NOT NULL,
    run_count   INTEGER NOT NULL DEFAULT 3,
    flaky_tests TEXT,
    pass_rate   REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mutation_cache (
    id              TEXT PRIMARY KEY,
    assessment_id   TEXT NOT NULL REFERENCES assessments(id),
    file_path       TEXT NOT NULL,
    mutant_id       TEXT NOT NULL,
    operator        TEXT NOT NULL,
    line_number     INTEGER,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id              TEXT PRIMARY KEY,
    assessment_id   TEXT NOT NULL REFERENCES assessments(id),
    outcome         TEXT NOT NULL,
    context         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# ── Migrations ───────────────────────────────────────────────────

# Add new migrations here as functions, then register in _MIGRATIONS.
# Pattern: def _migrate_vN_to_vN1(conn: sqlite3.Connection) -> None

_MIGRATIONS: dict[int, Any] = {
    # Example for future use:
    # 1: _migrate_v1_to_v2,
}


class VerdictStore:
    """SQLite-backed storage for Verdict data."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._run_migrations()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> VerdictStore:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store not opened. Call open() or use as context manager.")
        return self._conn

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA_SQL)
        cur = self.conn.execute(
            "SELECT value FROM verdict_meta WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO verdict_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    def _detect_schema_version(self) -> int:
        """Detect current schema version."""
        cur = self.conn.execute(
            "SELECT value FROM verdict_meta WHERE key = 'schema_version'"
        )
        row = cur.fetchone()
        if row:
            return int(row["value"])
        return 1

    def _run_migrations(self) -> None:
        """Run pending schema migrations."""
        current = self._detect_schema_version()
        if current >= SCHEMA_VERSION:
            return

        for version in range(current, SCHEMA_VERSION):
            migration = _MIGRATIONS.get(version)
            if migration:
                logger.info("Running migration v%d → v%d", version, version + 1)
                migration(self.conn)

        self.conn.execute(
            "INSERT OR REPLACE INTO verdict_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    # ── Assessments ──────────────────────────────────────────────

    def save_assessment(self, report: AssessmentReport) -> None:
        self.conn.execute(
            """INSERT INTO assessments
               (id, repo_path, ref_before, ref_after, files_changed,
                mutation_score, static_issues, sentinel_warnings,
                baseline_flaky, grade, report_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                report.repo_path,
                report.ref_before,
                report.ref_after,
                json.dumps(report.files_changed),
                report.mutation_score,
                report.static_issues,
                report.sentinel_warnings,
                report.baseline_flaky,
                report.overall_grade.value,
                report.to_json(),
                report.created_at,
            ),
        )
        for m in report.mutations:
            self._save_mutation(m, report.id)
        if report.baseline:
            self._save_baseline(report.baseline)
        self.conn.commit()

    def get_assessment(self, assessment_id: str) -> StoredAssessment | None:
        cur = self.conn.execute(
            "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_assessment(row)

    def get_assessments(
        self, limit: int = 20, offset: int = 0, repo_path: str | None = None
    ) -> list[StoredAssessment]:
        if repo_path:
            cur = self.conn.execute(
                """SELECT * FROM assessments WHERE repo_path = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (repo_path, limit, offset),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM assessments ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [self._row_to_assessment(r) for r in cur.fetchall()]

    def _row_to_assessment(self, row: sqlite3.Row) -> StoredAssessment:
        return StoredAssessment(
            id=row["id"],
            repo_path=row["repo_path"],
            ref_before=row["ref_before"],
            ref_after=row["ref_after"],
            files_changed=json.loads(row["files_changed"]),
            mutation_score=row["mutation_score"],
            static_issues=row["static_issues"],
            sentinel_warnings=row["sentinel_warnings"],
            baseline_flaky=row["baseline_flaky"] or 0,
            grade=row["grade"],
            report_json=row["report_json"],
            created_at=row["created_at"],
        )

    # ── Mutations ────────────────────────────────────────────────

    def _save_mutation(self, m: MutationResult, assessment_id: str) -> None:
        self.conn.execute(
            """INSERT INTO mutation_cache
               (id, assessment_id, file_path, mutant_id, operator,
                line_number, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                m.id,
                assessment_id,
                m.file_path,
                m.mutant_id,
                m.operator,
                m.line_number,
                m.status.value,
                m.created_at,
            ),
        )

    def get_mutations(self, assessment_id: str) -> list[StoredMutation]:
        cur = self.conn.execute(
            "SELECT * FROM mutation_cache WHERE assessment_id = ? ORDER BY file_path",
            (assessment_id,),
        )
        return [
            StoredMutation(
                id=r["id"],
                assessment_id=r["assessment_id"],
                file_path=r["file_path"],
                mutant_id=r["mutant_id"],
                operator=r["operator"],
                line_number=r["line_number"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in cur.fetchall()
        ]

    # ── Baselines ────────────────────────────────────────────────

    def _save_baseline(self, b: BaselineResult) -> None:
        self.conn.execute(
            """INSERT INTO baselines
               (id, repo_path, test_cmd, run_count, flaky_tests, pass_rate, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                b.id,
                b.repo_path,
                b.test_cmd,
                b.run_count,
                json.dumps(b.flaky_tests),
                b.pass_rate,
                b.created_at,
            ),
        )

    def get_latest_baseline(self, repo_path: str) -> StoredBaseline | None:
        cur = self.conn.execute(
            """SELECT * FROM baselines WHERE repo_path = ?
               ORDER BY created_at DESC LIMIT 1""",
            (repo_path,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return StoredBaseline(
            id=row["id"],
            repo_path=row["repo_path"],
            test_cmd=row["test_cmd"],
            run_count=row["run_count"],
            flaky_tests=json.loads(row["flaky_tests"]) if row["flaky_tests"] else [],
            pass_rate=row["pass_rate"],
            created_at=row["created_at"],
        )

    # ── Feedback ─────────────────────────────────────────────────

    def save_feedback(self, fb: Feedback) -> None:
        self.conn.execute(
            """INSERT INTO feedback (id, assessment_id, outcome, context, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (fb.id, fb.assessment_id, fb.outcome.value, fb.context, fb.created_at),
        )
        self.conn.commit()

    def get_feedback(self, assessment_id: str) -> list[StoredFeedback]:
        cur = self.conn.execute(
            "SELECT * FROM feedback WHERE assessment_id = ? ORDER BY created_at DESC",
            (assessment_id,),
        )
        return [
            StoredFeedback(
                id=r["id"],
                assessment_id=r["assessment_id"],
                outcome=r["outcome"],
                context=r["context"] or "",
                created_at=r["created_at"],
            )
            for r in cur.fetchall()
        ]

    # ── Stats ────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        tables = ["assessments", "baselines", "mutation_cache", "feedback"]
        result = {}
        for table in tables:
            cur = self.conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            result[table] = cur.fetchone()[0]
        return result
