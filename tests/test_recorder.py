"""Tests for session recording (src/context/recorder.py)."""

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _write_session_file(turns: int = 3) -> str:
    """Create a temp JSONL file with the given number of turns."""
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": f"Question {i}"},
            "timestamp": f"2026-02-10T12:0{i}:00Z",
            "sessionId": "test-session",
        }))
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": f"Answer {i}"}],
            },
            "timestamp": f"2026-02-10T12:0{i}:30Z",
            "sessionId": "test-session",
        }))

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines))
    f.close()
    return f.name


class TestRecordSession:
    """Tests for record_session."""

    @pytest.mark.asyncio
    async def test_stores_turns(self):
        """Recording a session stores all turns."""
        from src.context.recorder import record_session

        transcript = _write_session_file(turns=2)
        session = AsyncMock()

        # Mock: no existing session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        result = await record_session(
            session=session,
            session_id="test-session",
            transcript_path=transcript,
            workspace_path="/home/user/project",
        )

        assert result["turns_recorded"] == 2
        assert result["turns_skipped"] == 0
        # Should have added: 1 session + 2 turns + 2 contents = 5 adds
        assert session.add.call_count == 5

    @pytest.mark.asyncio
    async def test_deduplicates_by_hash(self):
        """Turns with existing content_hash are skipped."""
        from src.ingestion.claude_code import parse_session_into_turns
        from src.context.recorder import record_session

        transcript = _write_session_file(turns=2)

        # Get the actual hashes
        turns = parse_session_into_turns(Path(transcript))
        existing_hash = turns[0]["content_hash"]

        session = AsyncMock()

        # Mock: existing session with one turn already recorded
        mock_existing_turn = MagicMock()
        mock_existing_turn.content_hash = existing_hash

        mock_session_obj = MagicMock()
        mock_session_obj.turns = [mock_existing_turn]
        mock_session_obj.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_session_obj
        session.execute = AsyncMock(return_value=mock_result)

        result = await record_session(
            session=session,
            session_id="test-session",
            transcript_path=transcript,
            workspace_path="/home/user/project",
        )

        assert result["turns_skipped"] == 1
        assert result["turns_recorded"] == 1

    @pytest.mark.asyncio
    async def test_missing_file_returns_error(self):
        """Recording a nonexistent file returns error dict."""
        from src.context.recorder import record_session

        session = AsyncMock()

        result = await record_session(
            session=session,
            session_id="test",
            transcript_path="/nonexistent/file.jsonl",
            workspace_path="",
        )

        assert result["error"] == "file_not_found"
        assert result["turns_recorded"] == 0

    @pytest.mark.asyncio
    async def test_empty_session_returns_zero(self):
        """Recording an empty file returns zero turns."""
        from src.context.recorder import record_session

        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        f.close()

        session = AsyncMock()

        result = await record_session(
            session=session,
            session_id="empty",
            transcript_path=f.name,
            workspace_path="",
        )

        assert result["turns_recorded"] == 0


    @pytest.mark.asyncio
    async def test_new_session_does_not_lazy_load_turns(self):
        """Regression: P-008 — new session must not access .turns relationship.

        When a new AgentSession is created (not fetched from DB), accessing
        .turns triggers MissingGreenlet in async SQLAlchemy. The fix is to
        initialize existing_hashes = set() instead of iterating .turns.
        """
        from src.context.recorder import record_session

        transcript = _write_session_file(turns=1)
        session = AsyncMock()

        # Mock: no existing session (simulates new creation path)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        # This should NOT raise MissingGreenlet / greenlet_spawn error
        result = await record_session(
            session=session,
            session_id="new-session",
            transcript_path=transcript,
            workspace_path="/home/user/project",
        )

        assert result["turns_recorded"] == 1
        assert result["session_id"] == "new-session"


class TestEnqueueSessionRecording:
    """Tests for enqueue_session_recording."""

    @pytest.mark.asyncio
    async def test_enqueues_job(self):
        """Enqueue creates a session_process job."""
        from src.context.recorder import enqueue_session_recording

        mock_job = MagicMock()
        with patch("src.context.recorder.get_session") as mock_get_session, \
             patch("src.context.recorder.enqueue_job", new_callable=AsyncMock, return_value=mock_job) as mock_enqueue:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await enqueue_session_recording("sess-1", "/path/to.jsonl", "/home/user")

        assert result is True
        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args[1]
        assert call_kwargs["kind"] == "session_process"
        # Dedupe key includes file size for per-turn recording
        assert call_kwargs["dedupe_key"].startswith("session_process:sess-1:")

    @pytest.mark.asyncio
    async def test_dedupe_key_changes_with_file_size(self):
        """Each new turn changes file size, producing a unique dedupe key.

        This ensures the Stop hook (which fires per-turn) can enqueue a
        new recording job each time the transcript grows.
        """
        from src.context.recorder import enqueue_session_recording

        dedupe_keys = []

        mock_job = MagicMock()

        # First call: small file
        small_file = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        small_file.write('{"type":"user"}\n')
        small_file.close()

        with patch("src.context.recorder.get_session") as mock_gs, \
             patch("src.context.recorder.enqueue_job", new_callable=AsyncMock, return_value=mock_job) as mock_eq:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await enqueue_session_recording("sess-1", small_file.name, "/home/user")
            dedupe_keys.append(mock_eq.call_args[1]["dedupe_key"])

        # Second call: file grew (new turn appended)
        with open(small_file.name, "a") as f:
            f.write('{"type":"assistant"}\n{"type":"user"}\n')

        with patch("src.context.recorder.get_session") as mock_gs, \
             patch("src.context.recorder.enqueue_job", new_callable=AsyncMock, return_value=mock_job) as mock_eq:
            mock_gs.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_gs.return_value.__aexit__ = AsyncMock(return_value=False)
            await enqueue_session_recording("sess-1", small_file.name, "/home/user")
            dedupe_keys.append(mock_eq.call_args[1]["dedupe_key"])

        # Different file sizes → different dedupe keys → both get enqueued
        assert dedupe_keys[0] != dedupe_keys[1]
        assert all(k.startswith("session_process:sess-1:") for k in dedupe_keys)

    @pytest.mark.asyncio
    async def test_returns_false_on_duplicate(self):
        """Returns False when job is a duplicate."""
        from src.context.recorder import enqueue_session_recording

        with patch("src.context.recorder.get_session") as mock_get_session, \
             patch("src.context.recorder.enqueue_job", new_callable=AsyncMock, return_value=None):
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await enqueue_session_recording("sess-1", "/path/to.jsonl", "/home/user")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        """Returns False on database errors."""
        from src.context.recorder import enqueue_session_recording

        with patch("src.context.recorder.get_session", side_effect=Exception("db error")):
            result = await enqueue_session_recording("sess-1", "/path/to.jsonl", "/home/user")

        assert result is False
