# CLAUDE.md Generation — Design Document

## Philosophy

CLAUDE.md is the **primary context injection point** for every Claude Code session. It should be **rich, focused, and contextual** — not small. A new Claude session should be able to read CLAUDE.md and immediately have everything it needs to work effectively on the current project.

CLAUDE.md is NOT a slim router. It's a **focused briefing document** that contains real, actionable context. The problem with the translation project's 57KB CLAUDE.md wasn't size — it was **stale data, past versions, and unfocused dumping** of everything regardless of relevance.

### Principles

1. **CLAUDE.md should be rich** — include everything a fresh Claude needs to be productive immediately
2. **CLAUDE.md should be focused** — only include what's relevant to the current state of the project, not historical artifacts
3. **Maximalist data lives in docs/** — every decision, every domain fact, every schema version, every pitfall gets recorded somewhere permanent
4. **CLAUDE.md assembles from docs/** — the generator reads organized source files and composes the right briefing
5. **Stale data gets archived, not deleted** — old versions move to history files, not cluttering the active briefing
6. **Per-project organization** — each project gets its own docs directory with structured knowledge files

### What Belongs in CLAUDE.md

- Project identity and tech stack
- Current architecture (source tree, key patterns)
- Active sprint / in-progress work / blockers
- Coding conventions and mandatory rules
- Testing mandate (full, not compressed)
- All pitfalls (full text — these are critical for avoiding repeat mistakes)
- Active people context (who's involved right now)
- Recent decisions (last N, not all-time)
- Deep context references for further reading

### What Does NOT Belong in CLAUDE.md

- Complete character registries (translation project problem)
- Full historical decision log (just recent ones)
- Past versions of schema/architecture that no longer apply
- Domain knowledge dumps that aren't needed every session
- Cost analysis, academic references, and other reference material

### The Real Fix

The translation CLAUDE.md problem: it had the **complete character registry** (dozens of characters with full field tables), **complete schema** (6 tables fully documented), **all design decisions ever made**, **full domain knowledge** (cultivation realms, factions), and **content from when the project was a different app**. None of that was pruned when the project evolved.

The fix is NOT making CLAUDE.md smaller. It's:
1. **Organizing source data** in docs/ files that are the source of truth
2. **Smart assembly** — the generator reads docs/ and composes relevant content
3. **Temporal awareness** — recent decisions included, old ones referenced
4. **Project evolution** — when a project changes direction, stale sections get archived

## Architecture

### Source of Truth: `docs/` Directory

```
docs/
├── PITFALLS.md              # Cross-project pitfalls (always included in CLAUDE.md)
├── CONVENTIONS.md           # Coding conventions (always included)
├── TESTING.md               # Testing mandate and rules (always included)
├── ARCHITECTURE.md          # Current architecture tree + patterns (always included)
├── DECISIONS.md             # All decisions chronologically (recent N included in CLAUDE.md)
├── FEATURES.md              # Feature documentation
├── ROADMAP.md               # Future plans
├── CONTEXT-SYSTEM.md        # Context system deep docs
├── IDEAS.md                 # Ideas and brainstorming
├── CLAUDE-MD-DESIGN.md      # This file
└── projects/
    └── <slug>/
        ├── ARCHITECTURE.md  # Project-specific architecture (if different from root)
        ├── DECISIONS.md     # Project-specific decisions
        ├── DOMAIN.md        # Domain-specific knowledge (e.g., xianxia terms)
        ├── SCHEMA.md        # Database schema reference
        └── HISTORY.md       # Archived/superseded content
```

### Generator: `src/output/claude_md.py`

The generator assembles CLAUDE.md by:

1. **Reading docs/ files** — PITFALLS.md, CONVENTIONS.md, TESTING.md, ARCHITECTURE.md
2. **Querying the database** — current sprint, active tasks, blockers, people, sprints
3. **Composing sections** — each section pulls from the right source
4. **Including full content** where it matters (pitfalls, conventions, testing rules)
5. **Summarizing + referencing** where content is too large (domain knowledge, full decision history)

### Key Functions

```python
async def generate_claude_md(
    session: AsyncSession,
    project_slug: Optional[str] = None,
    output_path: Optional[Path] = None,
    generate_docs: bool = False,
) -> str:
    """Generate CLAUDE.md from docs/ files and database state.

    When generate_docs=True, also creates/updates the docs/ reference files.
    """
```

**Section assembly:**
- `_read_doc_file(path)` — reads a docs/ file, returns content (or empty string if missing)
- `_add_architecture_section(sections, docs_base)` — reads from `docs/ARCHITECTURE.md` instead of hardcoding
- `_add_conventions_section(sections, docs_base, session)` — reads from `docs/CONVENTIONS.md` with DB override
- `_add_testing_section(sections, docs_base)` — reads from `docs/TESTING.md` instead of hardcoding
- `_add_pitfalls_section(sections, docs_base)` — reads from `docs/PITFALLS.md` (already does this)
- `_add_recent_decisions(sections, docs_base, limit=10)` — reads last N entries from `docs/DECISIONS.md`
- `_add_current_sprint_section(session, sections, project)` — unchanged (DB query)
- `_add_blockers_section(session, sections, project)` — unchanged (DB query)
- `_add_people_section(session, sections, project)` — unchanged (DB query)

**Doc generation (when `generate_docs=True`):**
- `generate_project_docs(session, project_slug, docs_base)` — creates `docs/projects/<slug>/` with templates
- `_generate_architecture_doc(docs_base)` — introspects `src/` and writes `docs/ARCHITECTURE.md`

### What Changes vs Current

| Current | New |
|---------|-----|
| Architecture tree hardcoded in Python | Read from `docs/ARCHITECTURE.md` |
| Testing rules hardcoded in Python | Read from `docs/TESTING.md` |
| Conventions hardcoded with DB fallback | Read from `docs/CONVENTIONS.md` with DB override |
| Pitfalls inlined from file | Same (already reads from file) |
| No decisions section (placeholder) | Reads recent N from `docs/DECISIONS.md` |
| No per-project docs | `docs/projects/<slug>/` with organized files |
| People section always included | Only for project-specific generation |

### What Stays the Same

- CLAUDE.md is **rich** — full pitfalls, full conventions, full testing rules
- Dynamic sections from DB — current sprint, blockers, active sprints, people
- Written to `Path.cwd() / "CLAUDE.md"` by default
- Backward-compatible function signature

## CLI Integration

- `focus generate` — regenerates CLAUDE.md (reads from docs/ files)
- `focus generate --docs` — also regenerates the docs/ reference files
- `focus project docs <slug>` — creates/updates per-project docs directory
- `focus sync` — regenerates CLAUDE.md as part of normal sync (already does this)

## Testing

New file: `tests/test_claude_md.py`

- Test that CLAUDE.md reads architecture from `docs/ARCHITECTURE.md` not hardcoded
- Test that CLAUDE.md reads conventions from `docs/CONVENTIONS.md`
- Test that CLAUDE.md reads testing rules from `docs/TESTING.md`
- Test that CLAUDE.md includes full pitfalls content
- Test that sprint/blockers sections are dynamic from DB
- Test `_get_pitfall_count()` helper
- Test `_read_doc_file()` with missing/empty files
- Test `generate_project_docs()` creates directory structure
- Test `generate_docs=True` creates reference files
- Test backward-compatible signature (no `generate_docs` param)

## Migration

1. Create `docs/CONVENTIONS.md`, `docs/TESTING.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`
2. Refactor `claude_md.py` to read from these files
3. Run `focus generate` — produces CLAUDE.md assembled from docs/ files
4. All existing callers unchanged (backward-compatible)
5. Old CLAUDE.md overwritten with new version on next `focus sync`
