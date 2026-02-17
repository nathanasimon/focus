"""Tests for src/output/claude_md.py — docs-based CLAUDE.md generator."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_project, make_task

from src.output.claude_md import (
    _get_pitfall_count,
    _parse_recent_decisions,
    _read_doc_file,
    generate_claude_md,
    generate_project_docs,
)


# --- _read_doc_file ---


def test_read_doc_file_exists(tmp_path):
    """Returns stripped content when file exists."""
    f = tmp_path / "test.md"
    f.write_text("  hello world  \n")
    assert _read_doc_file(f) == "hello world"


def test_read_doc_file_missing(tmp_path):
    """Returns empty string when file does not exist."""
    assert _read_doc_file(tmp_path / "nope.md") == ""


def test_read_doc_file_empty(tmp_path):
    """Returns empty string when file is empty."""
    f = tmp_path / "empty.md"
    f.write_text("")
    assert _read_doc_file(f) == ""


# --- _get_pitfall_count ---


def test_get_pitfall_count(tmp_path):
    """Parses P-NNN headers and returns count + last id."""
    f = tmp_path / "PITFALLS.md"
    f.write_text("# Pitfalls\n\n## P-001: First\ntext\n\n## P-002: Second\ntext\n\n## P-003: Third\n")
    count, last = _get_pitfall_count(f)
    assert count == 3
    assert last == "P-003"


def test_get_pitfall_count_empty(tmp_path):
    """Returns (0, P-000) for file with no entries."""
    f = tmp_path / "PITFALLS.md"
    f.write_text("# Pitfalls\n\nNo entries yet.\n")
    count, last = _get_pitfall_count(f)
    assert count == 0
    assert last == "P-000"


def test_get_pitfall_count_missing_file(tmp_path):
    """Returns (0, P-000) when file does not exist."""
    count, last = _get_pitfall_count(tmp_path / "nope.md")
    assert count == 0
    assert last == "P-000"


# --- _parse_recent_decisions ---


def test_parse_recent_decisions_with_entries():
    """Extracts the last N decision entries."""
    content = (
        "# Decisions\n\nSome intro text.\n\n"
        "## 2026-01-01: First Decision\n**Context**: A\n\n"
        "## 2026-01-15: Second Decision\n**Context**: B\n\n"
        "## 2026-02-01: Third Decision\n**Context**: C\n"
    )
    result = _parse_recent_decisions(content, limit=2)
    assert "Second Decision" in result
    assert "Third Decision" in result
    assert "First Decision" not in result


def test_parse_recent_decisions_empty():
    """Returns empty string for content with no decision entries."""
    assert _parse_recent_decisions("# Decisions\n\nNothing here.\n") == ""


def test_parse_recent_decisions_none():
    """Returns empty string for empty content."""
    assert _parse_recent_decisions("") == ""


# --- generate_claude_md (integration) ---


def _make_mock_session():
    """Create a mock AsyncSession that returns empty results for all queries."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    return mock_session


@pytest.mark.asyncio
async def test_architecture_from_doc_file(tmp_path):
    """Architecture section reads from docs/ARCHITECTURE.md."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n\n```\nsrc/\n└── main.py\n```\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule one\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest everything.\n")

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "src/" in content
    assert "main.py" in content


@pytest.mark.asyncio
async def test_conventions_from_doc_file(tmp_path):
    """Conventions read from docs/CONVENTIONS.md when no DB override."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Always use type hints\n- Never use print\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest everything.\n")

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "Always use type hints" in content
    assert "Never use print" in content


@pytest.mark.asyncio
async def test_conventions_db_override(tmp_path):
    """DB UserPreference takes precedence over docs file."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- File convention\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest everything.\n")

    mock_pref = MagicMock()
    mock_pref.value = {"rules": ["DB rule one", "DB rule two"]}

    session = _make_mock_session()
    # The conventions query is the 4th execute call (after in_progress, waiting, backlog tasks,
    # then waiting again for blockers, then sprint, then conventions)
    # We need to make the UserPreference query return our mock
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        # The conventions query returns a UserPreference
        result.scalar_one_or_none.return_value = mock_pref if call_count == 6 else None
        return result

    session.execute = AsyncMock(side_effect=side_effect)
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "DB rule one" in content
    assert "DB rule two" in content
    assert "File convention" not in content


@pytest.mark.asyncio
async def test_testing_from_doc_file(tmp_path):
    """Testing rules read from docs/TESTING.md."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nCustom testing rules here.\n")

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "Custom testing rules here" in content


@pytest.mark.asyncio
async def test_pitfalls_inlined_full(tmp_path):
    """Full pitfall content appears in CLAUDE.md."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest.\n")
    (docs / "PITFALLS.md").write_text("# Pitfalls\n\n## P-001: Don't do X\n\nExplanation here.\n")

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "P-001: Don't do X" in content
    assert "Explanation here." in content


@pytest.mark.asyncio
async def test_recent_decisions_included(tmp_path):
    """Last N decisions from file appear in CLAUDE.md."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest.\n")
    (docs / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## 2026-02-01: Use SQLAlchemy async\n**Context**: Need async DB.\n"
    )

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "Use SQLAlchemy async" in content


@pytest.mark.asyncio
async def test_sprint_section_dynamic(tmp_path):
    """Mock DB with tasks, verify they appear in sprint section."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest.\n")

    task = make_task(status="in_progress", title="Fix critical bug")
    call_count = 0

    session = AsyncMock()

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        # First query is in_progress tasks
        if call_count == 1:
            result.scalars.return_value.all.return_value = [task]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=side_effect)
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "Fix critical bug" in content
    assert "IN PROGRESS:" in content


@pytest.mark.asyncio
async def test_blockers_section_dynamic(tmp_path):
    """Mock DB with waiting tasks, verify blockers section."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest.\n")

    waiting_task = make_task(status="waiting", title="Blocked on API key", waiting_since=None)
    call_count = 0

    session = AsyncMock()

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        # Queries 2 and 4 are waiting tasks (sprint waiting + blockers waiting)
        if call_count in (2, 4):
            result.scalars.return_value.all.return_value = [waiting_task]
        else:
            result.scalars.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=side_effect)
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "Blocked on API key" in content
    assert "## Blockers" in content


# --- generate_project_docs ---


@pytest.mark.asyncio
async def test_generate_project_docs_creates_dir(tmp_path):
    """Creates docs/projects/<slug>/ with template files."""
    docs = tmp_path / "docs"
    docs.mkdir()
    session = AsyncMock()

    result_dir = await generate_project_docs(session, "my-app", docs)

    assert result_dir == docs / "projects" / "my-app"
    assert (result_dir / "ARCHITECTURE.md").exists()
    assert (result_dir / "DECISIONS.md").exists()
    assert (result_dir / "DOMAIN.md").exists()
    assert "my-app" in (result_dir / "ARCHITECTURE.md").read_text()


@pytest.mark.asyncio
async def test_generate_project_docs_no_overwrite(tmp_path):
    """Existing files are not clobbered."""
    docs = tmp_path / "docs"
    project_dir = docs / "projects" / "my-app"
    project_dir.mkdir(parents=True)
    (project_dir / "DECISIONS.md").write_text("My custom decisions content\n")

    session = AsyncMock()
    await generate_project_docs(session, "my-app", docs)

    assert (project_dir / "DECISIONS.md").read_text() == "My custom decisions content\n"
    # But missing files are still created
    assert (project_dir / "ARCHITECTURE.md").exists()


# --- backward compat ---


@pytest.mark.asyncio
async def test_backward_compatible_signature(tmp_path):
    """generate_claude_md(session) works without new params."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n")
    (docs / "CONVENTIONS.md").write_text("# Conventions\n\n- Rule\n")
    (docs / "TESTING.md").write_text("# Testing (MANDATORY)\n\nTest.\n")

    session = _make_mock_session()
    output = tmp_path / "CLAUDE.md"

    with patch("src.output.claude_md.get_settings") as mock_settings:
        mock_settings.return_value.general.vault_path = tmp_path / "vault"
        # Call with only session + output_path (backward compatible)
        content = await generate_claude_md(session, output_path=output, docs_base=docs)

    assert "# CLAUDE.md — Focus" in content
    assert "## Project" in content
    assert "## Conventions" in content
