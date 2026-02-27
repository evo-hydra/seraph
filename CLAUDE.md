# Seraph — Code Quality Gate for AI-Generated Code

## What This Is

Seraph is an MCP server + CLI that assesses AI-generated code changes through a 7-step pipeline: diff parsing, flakiness baseline, mutation testing (mutmut), static analysis (ruff + mypy), Sentinel risk signals, multi-metric scoring, and SQLite persistence.

## Architecture

- **Entry points**: `seraph` (Typer CLI), `seraph-mcp` (FastMCP stdio server)
- **Core pipeline**: `src/seraph/core/engine.py` — `SeraphEngine.assess()` orchestrates all 7 steps
- **Configuration**: `src/seraph/config.py` — `SeraphConfig` frozen dataclass loaded from `.seraph/config.toml` → env vars → defaults
- **Storage**: SQLite with WAL mode at `.seraph/seraph.db` (schema v2 with indices)
- **Logging**: `src/seraph/logging_setup.py` — all output on stderr (MCP-safe), `--verbose` for DEBUG
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

All weights, thresholds, and deduction constants are configurable via `ScoringConfig` in `.seraph/config.toml` or env vars (e.g. `SERAPH_SCORING_MUTATION_WEIGHT=0.40`).

## Key Patterns

- **Subprocess isolation**: mutmut, ruff, mypy run as subprocesses — never import their internals
- **Graceful degradation**: Every external dep (Sentinel, mutmut, ruff, mypy) has try/except fallbacks with `logger.warning()` messages
- **Step isolation**: Each pipeline step (baseline, mutate, static, sentinel) is wrapped in try/except — a single step crash doesn't kill the pipeline
- **Tools return `str`**: MCP tools return formatted markdown, capped at ~4K tokens (configurable via `pipeline.max_output_chars`)
- **Dataclasses over Pydantic**: Models use stdlib `dataclasses` to keep deps minimal
- **Config priority**: env vars > `.seraph/config.toml` > dataclass defaults

## Testing

```bash
python3 -m pytest tests/ -v
```

All core modules have dedicated test files in `tests/core/`. Mocks used for subprocess calls (mutmut, ruff, mypy) and Sentinel imports.

## Commands

```bash
seraph assess [repo_path] --ref-before SHA --ref-after SHA --skip-baseline --skip-mutations --json --verbose
seraph history [repo_path] --limit N --offset N
seraph feedback <assessment-id> <accepted|rejected|modified> --context "..."
seraph prune [repo_path] --days N --yes
```

## MCP Tools

- `seraph_assess` — Full 7-step pipeline
- `seraph_mutate` — Mutation testing only
- `seraph_history` — Past assessments with pagination
- `seraph_feedback` — Submit feedback on an assessment

## Configuration

Place `.seraph/config.toml` in the repo root to override defaults:

```toml
[timeouts]
mutation_per_file = 300

[scoring]
mutation_weight = 0.40
static_weight = 0.15

[pipeline]
baseline_runs = 5

[retention]
retention_days = 30

[logging]
level = "DEBUG"
```

Env vars override TOML: `SERAPH_TIMEOUT_MUTATION_PER_FILE=300`, `SERAPH_SCORING_MUTATION_WEIGHT=0.40`, etc.

## Dependencies

- **Required**: typer, rich, tomli (Python < 3.11 only)
- **Optional**: `mcp` (MCP server), `git-sentinel` (Sentinel bridge), `mutmut` (mutation testing)
- **Dev**: pytest, pytest-cov, ruff, mypy

## Database

- Schema version: 2 (auto-migrates from v1)
- Indices on `assessments(repo_path, created_at)`, `mutation_cache(assessment_id)`, `baselines(repo_path)`, `feedback(assessment_id)`
- `seraph prune --days N` deletes old data in dependency order with VACUUM
