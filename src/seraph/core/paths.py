"""Shared path utilities for Seraph core modules."""

from __future__ import annotations

from pathlib import Path


def to_relative(path: str, repo_path: Path) -> str:
    """Convert absolute path to relative."""
    try:
        return str(Path(path).relative_to(repo_path))
    except ValueError:
        return path
