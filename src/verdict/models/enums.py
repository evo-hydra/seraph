"""Enums used across the Verdict system."""

from __future__ import annotations

from enum import Enum


class Grade(str, Enum):
    """Assessment grade for a scoring dimension."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"

    @classmethod
    def from_score(cls, score: float) -> Grade:
        if score >= 90:
            return cls.A
        if score >= 75:
            return cls.B
        if score >= 60:
            return cls.C
        if score >= 40:
            return cls.D
        return cls.F


class Severity(str, Enum):
    """Severity of a static analysis finding."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AnalyzerType(str, Enum):
    """Type of static analyzer."""

    RUFF = "ruff"
    MYPY = "mypy"


class FeedbackOutcome(str, Enum):
    """Outcome of feedback on an assessment."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"


class MutantStatus(str, Enum):
    """Status of a mutation test result."""

    KILLED = "killed"
    SURVIVED = "survived"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"
