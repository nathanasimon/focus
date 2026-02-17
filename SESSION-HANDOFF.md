# Session Handoff — CLAUDE.md Generator Redesign

> For a fresh Claude session to pick up and implement. Read this file completely before starting.

## What Is Focus

Focus is a local-first PKM system. Python 3.11, FastAPI, PostgreSQL, Typer CLI (`focus` command). It ingests emails/texts/docs, extracts structured data, and generates an Obsidian vault. The `focus` CLI lives at `/home/nathans/focus/.venv/bin/focus`.

The codebase is at `/home/nathans/focus/`. It has 538+ passing tests (`pytest tests/ -x -q`). Always read `CLAUDE.md` for full conventions. Every code change requires tests.

## The Task

Refactor `src/output/claude_md.py` so that it **reads content from organized `docs/` files** instead of having everything hardcoded in Python strings. CLAUDE.md output stays rich and full — this is NOT about making it smaller. It's about moving the source of truth to editable markdown files.

Read the full design doc: `docs/CLAUDE-MD-DESIGN.md`

## Why

Currently `claude_md.py` (370 lines) has:
- The entire architecture tree hardcoded as Python string literals (lines 78-104)
- The entire testing mandate hardcoded as Python string appends (lines 299-327)
- The entire conventions list hardcoded as Python string appends (lines 287-295)
- Pitfalls inlined by reading `docs/PITFALLS.md` (this part is already correct)
- A decisions section that's just a placeholder string

This means:
- To change conventions, you edit Python code instead of a markdown file
- Architecture tree is frozen in code, not reflecting actual source changes
- Testing rules are duplicated between code and what Claude sees
- No per-project documentation structure for projects Focus tracks

## Current State of Key Files

### `src/output/claude_md.py` (370 lines) — THE FILE TO REFACTOR

```python
async def generate_claude_md(
    session: AsyncSession,
    project_slug: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> str:
```

Sections it builds:
1. Header (project name, timestamp)
2. Project description (hardcoded for Focus, from DB for other projects)
3. **Architecture tree — HARDCODED lines 78-104** (move to `docs/ARCHITECTURE.md`)
4. Current Sprint — dynamic from DB via `_add_current_sprint_section()` (KEEP AS-IS)
5. Blockers — dynamic from DB via `_add_blockers_section()` (KEEP AS-IS)
6. Active Sprint — dynamic from DB via `_add_active_sprint_section()` (KEEP AS-IS)
7. **Conventions — HARDCODED lines 287-295** (move to `docs/CONVENTIONS.md`)
8. **Testing rules — HARDCODED lines 299-327** (move to `docs/TESTING.md`)
9. **Pitfalls — reads from `docs/PITFALLS.md`** (already correct pattern, keep)
10. Recent Decisions — placeholder string (read from `docs/DECISIONS.md`)
11. People — dynamic from DB via `_add_people_section()` (KEEP AS-IS)
12. Deep Context references

**Callers** (all backward-compatible, don't change these files):
- `src/cli/generate.py` line 34: `await generate_claude_md(session, project_slug=project)`
- `src/cli/sync_cmd.py`: `await generate_claude_md(session)`
- `src/daemon.py`: `await generate_claude_md(session)`
- `src/api/routes.py`: `await generate_claude_md(session, project_slug=project_slug)`

### `src/cli/generate.py` (40 lines)

Typer command. Add a `--docs` flag that passes `generate_docs=True` to the generator.

### `src/cli/project.py` (295 lines)

Has commands: list, pin, unpin, priority, deadline, use, unuse, sessions, create. Add a `docs` subcommand.

### `docs/` directory (existing files)

```
docs/PITFALLS.md        # 79 lines, P-001 through P-008
docs/FEATURES.md        # exists
docs/ROADMAP.md         # exists
docs/CONTEXT-SYSTEM.md  # exists
docs/IDEAS.md           # exists
docs/CLAUDE-MD-DESIGN.md # design doc for this task
```

### `tests/conftest.py`

Has fixtures: `make_email()`, `make_project()`, `make_task()`. You may need `make_sprint()`.

## Exactly What To Do

### Step 1: Create `docs/CONVENTIONS.md`

Extract from `claude_md.py` lines 287-295 (the hardcoded defaults in `_add_conventions_section`):

```markdown
# Conventions

- Type hints on all functions
- Explicit over implicit
- Functions under 50 lines
- Docstrings on public functions (Google style)
- snake_case everywhere
- Use `rich` for CLI output
- Use logging, not print()
- Prefer composition over inheritance
- Raw SQL only in migrations; use SQLAlchemy ORM elsewhere
```

### Step 2: Create `docs/TESTING.md`

Extract from `claude_md.py` lines 299-327 (full `_add_testing_section` content):

```markdown
# Testing (MANDATORY)

Every code change MUST include tests. No exceptions. Run `pytest tests/ -x -q` after writing them.

- **Bug fixes**: Write a regression test that fails without the fix and passes with it.
- **New functions**: Test happy path, edge cases (empty input, None, missing keys), and error paths.
- **Refactors**: Ensure existing tests still pass; add tests for any new branches.
- **Integration points** (DB, APIs, external services): Mock them. Tests must run without postgres/ollama/anthropic.
- **Async code**: Test concurrency-sensitive paths (e.g., multiple coroutines sharing state).

Structure:
- File per module: `tests/test_<module_name>.py`
- Use `conftest.py` fixtures: `make_email()`, `make_project()`, `make_task()`
- Mock external deps with `unittest.mock` / `AsyncMock`
- Aim for: every public function has at least one test, every branch has coverage

If you can verify a behavior by writing a test, write the test. Don't just fix and hope.

## Post-Mortem (MANDATORY)

When you cause a bug, introduce a regression, or discover a mistake in your own work:
1. Fix it and write a regression test
2. **Immediately** add a new entry to `docs/PITFALLS.md` (P-NNN format) explaining what went wrong and how to avoid it
3. Do NOT wait for `focus sync` — edit the file directly as part of the fix

This is not optional. The pitfalls file is your institutional memory. Every mistake not recorded is a mistake repeated.
```

### Step 3: Create `docs/ARCHITECTURE.md`

Extract from `claude_md.py` lines 78-104, plus add the context/ directory that was missing:

```markdown
# Architecture

\```
src/
├── ingestion/      # Gmail, Drive connectors
│   ├── gmail.py    # OAuth + incremental sync via historyId
│   └── accounts.py # Multi-account management
├── processing/     # Tiered AI pipeline
│   ├── classifier.py   # Ollama + Qwen3 4B (local, $0)
│   ├── extractor.py    # Claude Haiku (tasks, commitments, people)
│   ├── regex_parser.py # Automated email parsing ($0)
│   └── resolver.py     # Entity resolution + project linking
├── storage/        # Data layer
│   ├── db.py       # PostgreSQL via SQLAlchemy (async)
│   ├── models.py   # ORM models
│   └── raw.py      # Raw interaction archive
├── output/         # Markdown generation
│   ├── vault.py    # Obsidian vault generator
│   ├── kanban.py   # Per-project kanban boards
│   ├── daily.py    # Daily notes
│   ├── drafts.py   # Email draft suggestions
│   └── claude_md.py # CLAUDE.md generator
├── context/        # Claude Code context system
│   ├── classifier.py    # Prompt classification (local regex)
│   ├── retriever.py     # Context block retrieval from DB
│   ├── formatter.py     # Token-budget-aware formatting
│   ├── worker.py        # Background job processor
│   ├── project_state.py # Active project selection
│   └── artifact_extractor.py # JSONL artifact parser
├── api/            # FastAPI REST endpoints
├── cli/            # Typer CLI (focus command)
└── daemon.py       # Background sync daemon
\```

Key patterns: async throughout, SQLAlchemy 2.0 style, Pydantic models for all data, raw interactions stored permanently for reprocessing.
```

(Remove the backslash before the triple backticks — that's just escaping for this document.)

### Step 4: Create `docs/DECISIONS.md`

```markdown
# Decisions

Chronological log of design decisions. Recent entries are included in CLAUDE.md.

<!-- Add new decisions at the bottom. Format:
## YYYY-MM-DD: Decision Title
**Context**: Why this came up
**Decision**: What was decided
**Rationale**: Why
-->
```

### Step 5: Refactor `src/output/claude_md.py`

Key changes:

1. **Add `generate_docs: bool = False` parameter** to `generate_claude_md()`. Backward-compatible.

2. **Add `_read_doc_file(path: Path) -> str` helper** — reads a file, returns stripped content or empty string if missing.

3. **Replace hardcoded architecture** (lines 78-104) with `_add_architecture_section(sections, docs_base)` that calls `_read_doc_file(docs_base / "ARCHITECTURE.md")`.

4. **Replace hardcoded conventions** (`_add_conventions_section`) — still check DB `UserPreference` first for override, but fall back to reading `docs/CONVENTIONS.md` instead of hardcoded strings.

5. **Replace hardcoded testing** (`_add_testing_section`) with a version that reads from `docs/TESTING.md`.

6. **Replace decisions placeholder** with `_add_recent_decisions(sections, docs_base, limit=10)` that reads last N entries from `docs/DECISIONS.md`.

7. **Add `_get_pitfall_count(pitfalls_path) -> tuple[int, str]`** — parses `## P-NNN` headers, returns (count, last_id). Used for enriching the deep context reference.

8. **Add `generate_project_docs(session, project_slug, docs_base)`** — creates `docs/projects/<slug>/` with ARCHITECTURE.md, DECISIONS.md, DOMAIN.md templates. Only creates files that don't exist (never overwrites).

9. **When `generate_docs=True`**: call `generate_project_docs()` if a project_slug is provided.

**KEEP the `_add_pitfalls_section` behavior** — it already reads from file and inlines full content. This is the correct pattern. CLAUDE.md should have full pitfalls.

**The output CLAUDE.md should have the same rich content as before** — full pitfalls, full conventions, full testing rules, architecture tree. The difference is the *source* is docs/ files, not Python string literals.

### Step 6: Update `src/cli/generate.py`

Add `--docs` flag:
```python
docs: bool = typer.Option(False, "--docs", help="Also regenerate reference docs"),
```

Pass `generate_docs=docs` to `generate_claude_md()`.

### Step 7: Add `docs` subcommand to `src/cli/project.py`

```python
@app.command("docs")
def generate_project_docs_cmd(
    slug: str = typer.Argument(help="Project slug"),
):
    """Generate/update documentation for a project."""
    async def _gen():
        from src.output.claude_md import generate_project_docs
        from src.storage.db import get_session
        docs_base = Path(__file__).resolve().parent.parent.parent / "docs"
        async with get_session() as session:
            await generate_project_docs(session, slug, docs_base)
        console.print(f"[green]Docs generated for {slug}[/green]")
    asyncio.run(_gen())
```

### Step 8: Write `tests/test_claude_md.py`

Test the refactored generator. All tests should mock the DB session and use `tmp_path` for file operations. Key tests:

1. `test_read_doc_file_exists` — returns content
2. `test_read_doc_file_missing` — returns empty string
3. `test_get_pitfall_count` — parses P-NNN headers, returns (8, "P-008")
4. `test_get_pitfall_count_empty` — returns (0, "P-000")
5. `test_get_pitfall_count_missing_file` — returns (0, "P-000")
6. `test_architecture_from_doc_file` — architecture section reads from file, not hardcoded
7. `test_conventions_from_doc_file` — conventions read from file
8. `test_conventions_db_override` — DB UserPreference takes precedence over file
9. `test_testing_from_doc_file` — testing rules read from file
10. `test_pitfalls_inlined_full` — full pitfall content appears in CLAUDE.md
11. `test_sprint_section_dynamic` — mock DB with tasks, verify they appear
12. `test_blockers_section_dynamic` — mock DB with waiting tasks
13. `test_generate_project_docs_creates_dir` — creates `docs/projects/<slug>/`
14. `test_generate_project_docs_no_overwrite` — existing DECISIONS.md not clobbered
15. `test_recent_decisions_included` — last N decisions from file appear
16. `test_backward_compatible_signature` — `generate_claude_md(session)` works without new param

For DB-dependent tests, mock `AsyncSession` and SQLAlchemy results:
```python
from unittest.mock import AsyncMock, MagicMock, patch

mock_session = AsyncMock()
mock_result = MagicMock()
mock_result.scalars.return_value.all.return_value = [make_task(status="in_progress", title="Fix bug")]
mock_session.execute.return_value = mock_result
```

### Step 9: Run tests

```bash
cd /home/nathans/focus && .venv/bin/pytest tests/ -x -q
```

All 538+ existing tests plus new tests must pass.

## Important Constraints

- **CLAUDE.md output stays rich** — do NOT compress or slim down the output. The content should be the same as before (or richer). The change is where the source of truth lives.
- **Backward-compatible** — `generate_claude_md(session)` must work without the new parameter. All callers in sync_cmd.py, daemon.py, routes.py must continue working unchanged.
- **Every code change needs tests** — see CLAUDE.md testing mandate.
- **Functions under 50 lines** — break up if needed.
- **Use `logging`, not `print()`**
- **Pitfalls**: if you cause a bug, add to `docs/PITFALLS.md` immediately.

## Files You'll Touch

| File | Action |
|------|--------|
| `docs/CONVENTIONS.md` | CREATE — extract from claude_md.py |
| `docs/TESTING.md` | CREATE — extract from claude_md.py |
| `docs/ARCHITECTURE.md` | CREATE — extract from claude_md.py, add context/ dir |
| `docs/DECISIONS.md` | CREATE — empty template |
| `src/output/claude_md.py` | REFACTOR — read from docs/ files instead of hardcoding |
| `src/cli/generate.py` | EDIT — add `--docs` flag |
| `src/cli/project.py` | EDIT — add `docs` subcommand |
| `tests/test_claude_md.py` | CREATE — ~16 tests |

## Files To Read First

1. `CLAUDE.md` — project rules and conventions
2. `docs/CLAUDE-MD-DESIGN.md` — full design philosophy
3. `src/output/claude_md.py` — the file you're refactoring (370 lines, read it all)
4. `src/cli/generate.py` — caller to update (40 lines)
5. `src/cli/project.py` — caller to update (295 lines)
6. `tests/conftest.py` — existing test fixtures
7. `docs/PITFALLS.md` — existing reference doc pattern to follow
