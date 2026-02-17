"""End-to-end tests for the context system.

Tests the full pipeline: JSONL generation → recording → worker processing
→ classifier → retriever → formatter → hook output.

Includes both unit tests (mocked DB) and an integration test that hits
the real PostgreSQL database to verify the full stack works.
"""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Helpers: Generate realistic Claude Code JSONL transcripts ---


def _make_jsonl_session(
    session_id: str = "test-e2e-session",
    turns: list[tuple[str, str]] | None = None,
) -> str:
    """Create a realistic Claude Code JSONL transcript file.

    Args:
        session_id: Session identifier.
        turns: List of (user_message, assistant_response) tuples.
            If None, uses realistic defaults.

    Returns:
        Path to the temporary JSONL file.
    """
    if turns is None:
        turns = [
            (
                "What files are in the focus project?",
                "The focus project has modules in src/ including ingestion, processing, storage, output, and context.",
            ),
            (
                "Fix the bug in the pipeline where commitments are skipped",
                "I found the issue in src/ingestion/pipeline.py — the resolver gate only checked tasks and people but not commitments. Fixed by adding commitments to the condition.",
            ),
            (
                "Now run the tests to make sure everything passes",
                "All 403 tests pass. The regression test I added for the commitments gate also passes.",
            ),
        ]

    lines = []
    base_ts = "2026-02-11T10:{:02d}:{:02d}Z"
    minute = 0

    for i, (user_msg, assistant_msg) in enumerate(turns):
        # User message
        lines.append(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": user_msg},
            "timestamp": base_ts.format(minute, 0),
            "sessionId": session_id,
        }))
        minute += 1

        # Assistant response with text blocks
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_msg}],
                "model": "claude-opus-4-6",
            },
            "timestamp": base_ts.format(minute, 30),
            "sessionId": session_id,
        }))
        minute += 1

    # Add a sidechain message that should be filtered
    lines.append(json.dumps({
        "type": "assistant",
        "isSidechain": True,
        "message": {"role": "assistant", "content": "subagent internal"},
        "timestamp": base_ts.format(minute, 0),
        "sessionId": session_id,
    }))

    # Add a meta/command message that should be filtered
    lines.append(json.dumps({
        "type": "user",
        "isMeta": True,
        "message": {"role": "user", "content": "<command-name>help</command-name>"},
        "timestamp": base_ts.format(minute + 1, 0),
        "sessionId": session_id,
    }))

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines))
    f.close()
    return f.name


def _make_multi_turn_growing_session(session_id: str = "growing-session") -> list[str]:
    """Simulate a session growing turn by turn.

    Returns a list of file paths, each with one more turn than the last.
    This simulates what happens as Claude Code appends to the transcript.
    """
    turns = [
        ("Help me set up the database", "I'll create the schema with all the tables you need."),
        ("Add the context tables too", "Added agent_sessions, agent_turns, agent_turn_content, agent_turn_entities, and focus_jobs tables."),
        ("Now run the migrations", "All tables created successfully. Verified with a SELECT from pg_tables."),
    ]

    paths = []
    lines = []
    base_ts = "2026-02-11T14:{:02d}:{:02d}Z"
    minute = 0

    for user_msg, assistant_msg in turns:
        lines.append(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": user_msg},
            "timestamp": base_ts.format(minute, 0),
            "sessionId": session_id,
        }))
        minute += 1
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_msg}],
                "model": "claude-opus-4-6",
            },
            "timestamp": base_ts.format(minute, 30),
            "sessionId": session_id,
        }))
        minute += 1

        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.write("\n".join(lines))
        f.close()
        paths.append(f.name)

    return paths


# --- Unit Tests: JSONL Parser ---


class TestJSONLParser:
    """Tests for parse_session_into_turns from claude_code.py."""

    def test_parse_basic_session(self):
        """Parses a multi-turn session into structured turns."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session())
        turns = parse_session_into_turns(path)

        assert len(turns) == 3
        assert turns[0]["turn_number"] == 0
        assert turns[1]["turn_number"] == 1
        assert turns[2]["turn_number"] == 2

    def test_user_message_extracted(self):
        """User message text is captured."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[
            ("What is the meaning of life?", "42."),
        ]))
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert "meaning of life" in turns[0]["user_message"]

    def test_assistant_text_extracted(self):
        """Assistant text is captured from content blocks."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[
            ("Hi", "Hello! I'm Claude, here to help with your code."),
        ]))
        turns = parse_session_into_turns(path)

        assert "Hello" in turns[0]["assistant_text"]

    def test_sidechain_messages_filtered(self):
        """Sidechain (subagent) messages are excluded."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[("Q1", "A1")]))
        turns = parse_session_into_turns(path)

        # Only the main turn, not the sidechain message appended in helper
        assert len(turns) == 1

    def test_meta_messages_filtered(self):
        """Meta/command messages are excluded."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[("Q1", "A1")]))
        turns = parse_session_into_turns(path)

        for turn in turns:
            assert "<command-name>" not in (turn.get("user_message") or "")

    def test_content_hash_deterministic(self):
        """Same content produces same hash."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(session_id="hash-test"))
        turns_a = parse_session_into_turns(path)
        turns_b = parse_session_into_turns(path)

        for a, b in zip(turns_a, turns_b):
            assert a["content_hash"] == b["content_hash"]

    def test_content_hash_unique_per_turn(self):
        """Different turns produce different hashes."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session())
        turns = parse_session_into_turns(path)

        hashes = [t["content_hash"] for t in turns]
        assert len(hashes) == len(set(hashes))

    def test_model_name_captured(self):
        """Model name is extracted from assistant messages."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[("Hi", "Hello")]))
        turns = parse_session_into_turns(path)

        assert turns[0]["model_name"] == "claude-opus-4-6"

    def test_timestamps_captured(self):
        """Start and end timestamps are captured."""
        from src.ingestion.claude_code import parse_session_into_turns

        path = Path(_make_jsonl_session(turns=[("Hi", "Hello")]))
        turns = parse_session_into_turns(path)

        assert turns[0]["started_at"] is not None
        assert turns[0]["ended_at"] is not None

    def test_empty_file_returns_empty(self):
        """Empty file returns no turns."""
        from src.ingestion.claude_code import parse_session_into_turns

        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.close()

        turns = parse_session_into_turns(Path(f.name))
        assert turns == []

    def test_nonexistent_file_returns_empty(self):
        """Missing file returns no turns."""
        from src.ingestion.claude_code import parse_session_into_turns

        turns = parse_session_into_turns(Path("/nonexistent/session.jsonl"))
        assert turns == []


# --- Unit Tests: Classifier ---


class TestClassifier:
    """Tests for PromptClassifier."""

    @pytest.mark.asyncio
    async def test_workspace_set_from_cwd(self):
        """Workspace project is always set from cwd, even without DB match."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = [("other-proj", "Other Project")]
        classifier._people = []

        result = classifier.classify("fix the bug", cwd="/home/user/my-project")

        assert result.workspace_project == "my-project"

    @pytest.mark.asyncio
    async def test_project_slug_match(self):
        """Project slug in prompt is detected."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = [("focus", "Focus")]
        classifier._people = []

        result = classifier.classify("what's the status of focus?")

        assert "focus" in result.project_slugs
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_person_name_match(self):
        """Person name in prompt is detected."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = []
        classifier._people = [("Nathan Simon", "nathan@example.com")]

        result = classifier.classify("what did Nathan Simon say about the deadline?")

        assert "Nathan Simon" in result.person_names
        assert result.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_query_type_code(self):
        """Code-related prompts are classified as 'code'."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = []
        classifier._people = []

        result = classifier.classify("fix the bug in the test module")
        assert result.query_type == "code"

    @pytest.mark.asyncio
    async def test_query_type_email(self):
        """Email-related prompts are classified as 'email'."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = []
        classifier._people = []

        result = classifier.classify("draft a reply to the email")
        assert result.query_type == "email"

    @pytest.mark.asyncio
    async def test_query_type_task(self):
        """Task-related prompts are classified as 'task'."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = []
        classifier._people = []

        result = classifier.classify("what's on the backlog for the sprint?")
        assert result.query_type == "task"

    @pytest.mark.asyncio
    async def test_empty_prompt_low_confidence(self):
        """Empty/short prompts get no classification."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = []
        classifier._people = []

        result = classifier.classify("")
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_confidence_stacking(self):
        """Workspace alone gets 0.5; with project match gets higher."""
        from src.context.classifier import PromptClassifier

        classifier = PromptClassifier()
        classifier._loaded = True
        classifier._projects = [("focus", "Focus")]
        classifier._people = []

        # Workspace only (no project mention in prompt)
        result = classifier.classify("help me with this", cwd="/home/user/focus")
        assert result.confidence >= 0.3

        # Project in prompt
        result = classifier.classify("what's the status of focus?", cwd="/home/user/focus")
        assert result.confidence >= 0.8


# --- Unit Tests: Formatter ---


class TestFormatter:
    """Tests for context formatter."""

    def test_empty_blocks_returns_empty(self):
        """No blocks = empty string."""
        from src.context.formatter import format_context_blocks

        assert format_context_blocks([]) == ""

    def test_includes_header(self):
        """Output starts with Focus Context header."""
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextBlock

        blocks = [ContextBlock("task", "1", "Test", "Some task content", 0.8)]
        result = format_context_blocks(blocks)

        assert result.startswith("## Focus Context")

    def test_type_labels(self):
        """Each source type gets correct label prefix."""
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextBlock

        blocks = [
            ContextBlock("conversation", "1", "T", "conv content", 0.8),
            ContextBlock("task", "2", "T", "task content", 0.7),
            ContextBlock("commitment", "3", "T", "commit content", 0.6),
        ]
        result = format_context_blocks(blocks, max_tokens=5000)

        assert "[Conv]" in result
        assert "[Task]" in result
        assert "[Commitment]" in result

    def test_token_budget_respected(self):
        """Blocks exceeding token budget are excluded with overflow note."""
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextBlock

        blocks = [
            ContextBlock("task", "1", "T1", "A" * 200, 0.9),
            ContextBlock("task", "2", "T2", "B" * 200, 0.8),
            ContextBlock("task", "3", "T3", "C" * 200, 0.7),
        ]
        # Very tight budget: only room for ~1 block
        result = format_context_blocks(blocks, max_tokens=80)

        assert "+2 more" in result or "+1 more" in result

    def test_sorted_by_relevance(self):
        """Higher relevance blocks appear first."""
        from src.context.formatter import format_context_blocks
        from src.context.retriever import ContextBlock

        blocks = [
            ContextBlock("task", "1", "T", "low priority", 0.3),
            ContextBlock("task", "2", "T", "high priority", 0.9),
        ]
        result = format_context_blocks(blocks, max_tokens=5000)

        high_pos = result.index("high priority")
        low_pos = result.index("low priority")
        assert high_pos < low_pos


# --- Unit Tests: Per-Turn Recording ---


class TestPerTurnRecording:
    """Tests that recording works incrementally as the transcript grows."""

    @pytest.mark.asyncio
    async def test_growing_session_records_incrementally(self):
        """Each new turn in a growing transcript is recorded (not deduplicated)."""
        from src.context.recorder import record_session

        paths = _make_multi_turn_growing_session()

        # Track all recorded turn counts across iterations
        total_recorded = 0

        for i, path in enumerate(paths):
            session_mock = AsyncMock()
            mock_result = MagicMock()

            if i == 0:
                # First iteration: no existing session
                mock_result.scalar_one_or_none.return_value = None
                session_mock.execute = AsyncMock(return_value=mock_result)
            else:
                # Subsequent iterations: session exists with prior turns
                existing_turns = []
                from src.ingestion.claude_code import parse_session_into_turns
                prior_turns = parse_session_into_turns(Path(paths[i - 1]))
                for t in prior_turns:
                    mock_turn = MagicMock()
                    mock_turn.content_hash = t["content_hash"]
                    existing_turns.append(mock_turn)

                mock_session_obj = MagicMock()
                mock_session_obj.turns = existing_turns
                mock_session_obj.id = uuid.uuid4()
                mock_result.scalar_one_or_none.return_value = mock_session_obj
                session_mock.execute = AsyncMock(return_value=mock_result)

            result = await record_session(
                session=session_mock,
                session_id="growing-session",
                transcript_path=path,
                workspace_path="-home-user-focus",
            )

            if i == 0:
                # First run: all turns are new
                assert result["turns_recorded"] == 1
            else:
                # Subsequent runs: only 1 new turn
                assert result["turns_recorded"] == 1
                assert result["turns_skipped"] == i

            total_recorded += result["turns_recorded"]

        # Total across all runs should equal total turns
        assert total_recorded == 3

    @pytest.mark.asyncio
    async def test_dedupe_key_includes_file_size(self):
        """Enqueue creates unique dedupe key per file size."""
        from src.context.recorder import enqueue_session_recording

        paths = _make_multi_turn_growing_session()
        dedupe_keys = []

        for path in paths:
            mock_job = MagicMock()
            with patch("src.context.recorder.get_session") as mock_gs, \
                 patch("src.context.recorder.enqueue_job", new_callable=AsyncMock, return_value=mock_job) as mock_eq:
                mock_gs.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
                mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
                await enqueue_session_recording("growing-session", path, "/home/user")
                dedupe_keys.append(mock_eq.call_args[1]["dedupe_key"])

        # All dedupe keys should be unique (different file sizes)
        assert len(dedupe_keys) == len(set(dedupe_keys))


# --- Unit Tests: Hook I/O ---


class TestHookIO:
    """Tests for the hook input/output contract."""

    def test_retrieve_hook_outputs_valid_json(self):
        """Retrieve hook produces valid JSON with correct structure."""
        from src.cli.retrieve_cmd import _hook_retrieve

        input_data = json.dumps({
            "prompt": "Fix the pipeline bug",
            "session_id": "test-session",
            "cwd": "/home/user/focus",
        })

        captured = []
        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.print", side_effect=captured.append), \
             patch("asyncio.run") as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = input_data
            mock_run.return_value = "## Focus Context\n\n[Task] Fix the thing"
            _hook_retrieve()

        assert exc_info.value.code == 0
        assert len(captured) == 1

        output = json.loads(captured[0])
        assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "Focus Context" in output["hookSpecificOutput"]["additionalContext"]

    def test_record_hook_reads_session_from_stdin(self):
        """Record hook reads session_id and transcript_path from stdin."""
        from src.cli.record_cmd import _hook_record

        input_data = json.dumps({
            "session_id": "test-session-123",
            "transcript_path": "/home/user/.claude/projects/proj/session.jsonl",
            "cwd": "/home/user/proj",
        })

        with patch("sys.stdin") as mock_stdin, \
             patch("asyncio.run") as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = input_data
            _hook_record()

        assert exc_info.value.code == 0
        # asyncio.run was called (the enqueue coroutine)
        mock_run.assert_called_once()


# --- Integration Test: Full Pipeline Against Real DB ---


@pytest.fixture(autouse=True)
def _reset_db_engine():
    """Reset the DB engine singleton between tests to avoid event loop issues."""
    import src.storage.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    yield
    db_mod._engine = None
    db_mod._session_factory = None


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("FOCUS_SKIP_DB_TESTS", "0") == "1",
    reason="Database not available",
)
class TestContextIntegration:
    """Integration tests that hit the real PostgreSQL database.

    These create a real session, record it, process it, and verify
    the full pipeline from recording through retrieval.
    """

    async def test_full_pipeline(self):
        """Create session → record → classify → retrieve → format."""
        from src.context.classifier import PromptClassifier
        from src.context.formatter import format_context_blocks
        from src.context.recorder import record_session
        from src.context.retriever import ContextRetriever
        from src.storage.db import get_session
        from src.storage.models import AgentSession, AgentTurn

        test_session_id = f"integration-test-{uuid.uuid4().hex[:8]}"

        # 1. Create a realistic JSONL transcript
        transcript_path = _make_jsonl_session(
            session_id=test_session_id,
            turns=[
                ("List all files in the focus project", "The project has src/, tests/, web/, and docs/ directories."),
                ("Fix the bug in pipeline.py", "Found and fixed the resolver gate bug — it wasn't checking commitments."),
            ],
        )

        try:
            # 2. Record the session into the database
            async with get_session() as session:
                result = await record_session(
                    session=session,
                    session_id=test_session_id,
                    transcript_path=transcript_path,
                    workspace_path="-home-nathans-focus",
                )

            assert result["turns_recorded"] == 2
            assert result["turns_skipped"] == 0

            # 3. Verify session and turns exist in DB
            async with get_session() as session:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload

                agent_session = (await session.execute(
                    select(AgentSession)
                    .options(selectinload(AgentSession.turns))
                    .where(AgentSession.session_id == test_session_id)
                )).scalar_one_or_none()

                assert agent_session is not None
                assert agent_session.turn_count == 2
                assert agent_session.workspace_path == "-home-nathans-focus"
                assert len(agent_session.turns) == 2

                # Verify turn content
                turns = sorted(agent_session.turns, key=lambda t: t.turn_number)
                assert "focus project" in turns[0].user_message
                assert "pipeline" in turns[1].user_message

                # Verify content hashes are unique
                hashes = [t.content_hash for t in turns]
                assert len(hashes) == len(set(hashes))

            # 4. Classify a prompt
            async with get_session() as session:
                classifier = PromptClassifier()
                await classifier.load_entities(session)

                classification = classifier.classify(
                    "what happened with the pipeline bug?",
                    cwd="/home/nathans/focus",
                )

                assert classification.workspace_project == "focus"
                assert classification.query_type == "code"
                assert classification.confidence >= 0.3

            # 5. Retrieve context
            async with get_session() as session:
                retriever = ContextRetriever()
                blocks = await retriever.retrieve(session, classification)

                # Should find at least the turns we just recorded
                assert len(blocks) > 0

                # Check that conversation blocks are present
                conv_blocks = [b for b in blocks if b.source_type == "conversation"]
                assert len(conv_blocks) > 0

            # 6. Format the context
            formatted = format_context_blocks(blocks)

            assert formatted.startswith("## Focus Context")
            assert "[Conv]" in formatted
            assert len(formatted) > 50

        finally:
            # Cleanup: remove the test session
            try:
                async with get_session() as session:
                    from sqlalchemy import delete

                    agent_session = (await session.execute(
                        select(AgentSession)
                        .where(AgentSession.session_id == test_session_id)
                    )).scalar_one_or_none()

                    if agent_session:
                        await session.execute(
                            delete(AgentTurn).where(AgentTurn.session_id == agent_session.id)
                        )
                        await session.execute(
                            delete(AgentSession).where(AgentSession.id == agent_session.id)
                        )
            except Exception:
                pass
            os.unlink(transcript_path)

    async def test_incremental_recording(self):
        """Recording a growing session incrementally adds only new turns."""
        from src.context.recorder import record_session
        from src.storage.db import get_session
        from src.storage.models import AgentSession, AgentTurn

        test_session_id = f"incremental-test-{uuid.uuid4().hex[:8]}"
        paths = _make_multi_turn_growing_session(session_id=test_session_id)

        try:
            for i, path in enumerate(paths):
                async with get_session() as session:
                    result = await record_session(
                        session=session,
                        session_id=test_session_id,
                        transcript_path=path,
                        workspace_path="-home-test",
                    )

                assert result["turns_recorded"] == 1, f"Iteration {i}: expected 1 new turn"
                assert result["turns_skipped"] == i, f"Iteration {i}: expected {i} skipped"

            # Verify final state
            async with get_session() as session:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload

                agent_session = (await session.execute(
                    select(AgentSession)
                    .options(selectinload(AgentSession.turns))
                    .where(AgentSession.session_id == test_session_id)
                )).scalar_one_or_none()

                assert agent_session is not None
                assert agent_session.turn_count == 3
                assert len(agent_session.turns) == 3

        finally:
            try:
                async with get_session() as session:
                    from sqlalchemy import delete

                    agent_session = (await session.execute(
                        select(AgentSession)
                        .where(AgentSession.session_id == test_session_id)
                    )).scalar_one_or_none()

                    if agent_session:
                        await session.execute(
                            delete(AgentTurn).where(AgentTurn.session_id == agent_session.id)
                        )
                        await session.execute(
                            delete(AgentSession).where(AgentSession.id == agent_session.id)
                        )
            except Exception:
                pass
            for p in paths:
                os.unlink(p)

    async def test_hook_settings_configured(self):
        """Verify Claude Code hooks are properly configured in settings.json."""
        settings_path = Path.home() / ".claude" / "settings.json"
        assert settings_path.exists(), "~/.claude/settings.json does not exist"

        with open(settings_path) as f:
            settings = json.load(f)

        assert "hooks" in settings, "No hooks key in settings.json"

        # Stop hook
        assert "Stop" in settings["hooks"], "No Stop hook configured"
        stop_hooks = settings["hooks"]["Stop"]
        assert len(stop_hooks) > 0
        stop_cmd = stop_hooks[0]["hooks"][0]["command"]
        assert "focus" in stop_cmd and "record" in stop_cmd

        # UserPromptSubmit hook
        assert "UserPromptSubmit" in settings["hooks"], "No UserPromptSubmit hook configured"
        submit_hooks = settings["hooks"]["UserPromptSubmit"]
        assert len(submit_hooks) > 0
        submit_cmd = submit_hooks[0]["hooks"][0]["command"]
        assert "focus" in submit_cmd and "retrieve" in submit_cmd

    async def test_worker_is_running(self):
        """Verify the context worker process is running."""
        pid_file = Path.home() / ".config" / "focus" / "worker.pid"

        assert pid_file.exists(), "Worker PID file does not exist. Run: focus worker start --daemon"

        pid = int(pid_file.read_text().strip())

        # Check process exists
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pytest.fail(f"Worker process (PID {pid}) is not running")

    async def test_context_stats_populated(self):
        """Verify that the database has recorded sessions and turns."""
        from sqlalchemy import func, select

        from src.storage.db import get_session
        from src.storage.models import AgentSession, AgentTurn

        async with get_session() as session:
            session_count = (await session.execute(
                select(func.count()).select_from(AgentSession)
            )).scalar()

            turn_count = (await session.execute(
                select(func.count()).select_from(AgentTurn)
            )).scalar()

        assert session_count > 0, "No agent sessions recorded"
        assert turn_count > 0, "No agent turns recorded"
