"""Shared test fixtures for Verdict."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from verdict.core.store import VerdictStore


def _git(repo_path: Path, *args: str) -> None:
    """Run a git command in the given repo, raising on failure."""
    subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("# Test Repo\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.fixture
def store(tmp_path: Path) -> VerdictStore:
    """Create a temporary VerdictStore."""
    db_path = tmp_path / ".verdict" / "verdict.db"
    s = VerdictStore(db_path)
    s.open()
    yield s
    s.close()


@pytest.fixture
def sample_diff_text() -> str:
    """A sample git diff output for testing."""
    return """\
diff --git a/src/foo.py b/src/foo.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/foo.py
@@ -0,0 +1,10 @@
+def hello():
+    return "world"
+
+def add(a, b):
+    return a + b
diff --git a/src/bar.py b/src/bar.py
index abc1234..def5678 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -5,3 +5,7 @@ def existing():
+def new_func():
+    pass
+
@@ -15,2 +19,0 @@ def another():
-    old_line1
-    old_line2
diff --git a/README.md b/README.md
index 111..222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-# Old Title
+# New Title
"""
