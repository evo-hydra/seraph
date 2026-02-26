# Verdict — Verification Intelligence for AI-Generated Code

## What This Is

Verdict is an MCP server + CLI that assesses AI-generated code changes through a 7-step pipeline: diff parsing, flakiness baseline, mutation testing (mutmut), static analysis (ruff + mypy), Sentinel risk signals, multi-metric scoring, and SQLite persistence.

## Architecture

- **Entry points**: `verdict` (Typer CLI), `verdict-mcp` (FastMCP stdio server)
- **Core pipeline**: `src/verdict/core/engine.py` — `VerdictEngine.assess()` orchestrates all 7 steps
- **Storage**: SQLite with WAL mode at `.verdict/verdict.db`
- **Sentinel integration**: `bridge.py` imports `sentinel.core.knowledge.KnowledgeStore` directly (Python dep, not MCP-to-MCP)

## Scoring Model

5 dimensions with weighted grades (A-F):

| Dimension | Weight | Source |
|-----------|--------|--------|
| Mutation Score | 30% | mutmut killed/total |
| Static Cleanliness | 20% | ruff + mypy issues/file |
| Test Baseline | 15% | flaky test rate |
| Sentinel Risk | 20% | hot files + pitfall matches |
| Co-change Coverage | 15% | touched files vs co-change partners |

Thresholds: A ≥ 90, B ≥ 75, C ≥ 60, D ≥ 40, F < 40

## Key Patterns

- **Subprocess isolation**: mutmut, ruff, mypy run as subprocesses — never import their internals
- **Graceful degradation**: Every external dep (Sentinel, mutmut, ruff, mypy) has try/except fallbacks
- **Tools return `str`**: MCP tools return formatted markdown, capped at ~4K tokens (16K chars)
- **Dataclasses over Pydantic**: Models use stdlib `dataclasses` to keep deps minimal

## Testing

```bash
python3 -m pytest tests/ -v
```

All core modules have dedicated test files in `tests/core/`. Mocks used for subprocess calls (mutmut, ruff, mypy) and Sentinel imports.

## Commands

```bash
verdict assess [repo_path] --ref-before SHA --ref-after SHA --skip-baseline --skip-mutations --json
verdict history [repo_path] --limit N --offset N
verdict feedback <assessment-id> <accepted|rejected|modified> --context "..."
```

## MCP Tools

- `verdict_assess` — Full 7-step pipeline
- `verdict_mutate` — Mutation testing only
- `verdict_history` — Past assessments with pagination
- `verdict_feedback` — Submit feedback on an assessment

## Dependencies

- **Required**: typer, rich
- **Optional**: `mcp` (MCP server), `git-sentinel` (Sentinel bridge), `mutmut` (mutation testing)
- **Dev**: pytest, pytest-cov, ruff, mypy
