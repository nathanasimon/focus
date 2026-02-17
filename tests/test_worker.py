"""Tests for the background worker (src/context/worker.py)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.models import FocusJob


def make_job(**overrides):
    """Create a mock FocusJob."""
    defaults = {
        "id": uuid.uuid4(),
        "kind": "session_process",
        "payload": {"session_id": "test-session", "transcript_path": "/tmp/test.jsonl", "workspace_path": "/home/user"},
        "status": "processing",
        "attempts": 1,
        "max_attempts": 10,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=FocusJob)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestDispatchJob:
    """Tests for _dispatch_job."""

    @pytest.mark.asyncio
    async def test_dispatches_session_process(self):
        """session_process jobs dispatch to process_session_job."""
        from src.context.worker import _dispatch_job

        job = make_job(kind="session_process")

        with patch("src.context.worker.process_session_job", new_callable=AsyncMock) as mock_handler:
            await _dispatch_job(job)

        mock_handler.assert_called_once_with(job)

    @pytest.mark.asyncio
    async def test_dispatches_turn_summary(self):
        """turn_summary jobs dispatch to process_turn_summary_job."""
        from src.context.worker import _dispatch_job

        job = make_job(kind="turn_summary", payload={"turn_id": str(uuid.uuid4())})

        with patch("src.context.worker.process_turn_summary_job", new_callable=AsyncMock) as mock_handler:
            await _dispatch_job(job)

        mock_handler.assert_called_once_with(job)

    @pytest.mark.asyncio
    async def test_dispatches_entity_extract(self):
        """entity_extract jobs dispatch to process_entity_extract_job."""
        from src.context.worker import _dispatch_job

        job = make_job(kind="entity_extract", payload={"turn_id": str(uuid.uuid4())})

        with patch("src.context.worker.process_entity_extract_job", new_callable=AsyncMock) as mock_handler:
            await _dispatch_job(job)

        mock_handler.assert_called_once_with(job)

    @pytest.mark.asyncio
    async def test_unknown_kind_raises(self):
        """Unknown job kind raises ValueError."""
        from src.context.worker import _dispatch_job

        job = make_job(kind="unknown_kind")

        with pytest.raises(ValueError, match="Unknown job kind"):
            await _dispatch_job(job)


class TestProcessSessionJob:
    """Tests for process_session_job."""

    @pytest.mark.asyncio
    async def test_calls_record_session(self):
        """Session job calls record_session with correct args."""
        from src.context.worker import process_session_job

        job = make_job(
            kind="session_process",
            payload={
                "session_id": "sess-123",
                "transcript_path": "/tmp/test.jsonl",
                "workspace_path": "/home/user/project",
            },
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.context.worker.get_session") as mock_get_session, \
             patch("src.context.recorder.record_session", new_callable=AsyncMock) as mock_record, \
             patch("src.context.worker._link_session_to_project", new_callable=AsyncMock), \
             patch("src.storage.jobs.enqueue_job", new_callable=AsyncMock):
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_record.return_value = {"turns_recorded": 3, "turns_skipped": 0}

            # Mock the inner queries for enqueuing child jobs
            mock_agent_session = MagicMock()
            mock_agent_session.id = uuid.uuid4()

            mock_turns_result = MagicMock()
            mock_turns_result.scalars.return_value.all.return_value = []

            mock_session_result = MagicMock()
            mock_session_result.scalar_one_or_none.return_value = mock_agent_session

            mock_session.execute = AsyncMock(side_effect=[mock_session_result, mock_turns_result])

            await process_session_job(job)

        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args[1]
        assert call_kwargs["session_id"] == "sess-123"
        assert call_kwargs["transcript_path"] == "/tmp/test.jsonl"


class TestProcessTurnSummaryJob:
    """Tests for process_turn_summary_job."""

    @pytest.mark.asyncio
    async def test_short_message_uses_truncation(self):
        """Short user messages get simple truncation, not LLM."""
        from src.context.worker import process_turn_summary_job

        turn_id = uuid.uuid4()
        job = make_job(kind="turn_summary", payload={"turn_id": str(turn_id)})

        mock_turn = MagicMock()
        mock_turn.user_message = "Fix bug"
        mock_turn.assistant_summary = None
        mock_turn.turn_title = None

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_turn)

        with patch("src.context.worker.get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_turn_summary_job(job)

        assert mock_turn.turn_title == "Fix bug"

    @pytest.mark.asyncio
    async def test_missing_turn_is_skipped(self):
        """Job for nonexistent turn is silently skipped."""
        from src.context.worker import process_turn_summary_job

        job = make_job(kind="turn_summary", payload={"turn_id": str(uuid.uuid4())})

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        with patch("src.context.worker.get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_turn_summary_job(job)

        # No error should have been raised


class TestProcessEntityExtractJob:
    """Tests for process_entity_extract_job."""

    @pytest.mark.asyncio
    async def test_finds_project_mention(self):
        """Detects project slug mentions in turn text."""
        from src.context.worker import process_entity_extract_job

        turn_id = uuid.uuid4()
        project_id = uuid.uuid4()
        job = make_job(kind="entity_extract", payload={"turn_id": str(turn_id)})

        mock_turn = MagicMock()
        mock_turn.user_message = "Fix the bug in focus project"
        mock_content = MagicMock()
        mock_content.assistant_text = "I'll look at the focus codebase"
        mock_turn.content = mock_content

        mock_project = MagicMock()
        mock_project.id = project_id
        mock_project.slug = "focus"
        mock_project.name = "Focus"

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_turn)

        # Mock project query
        mock_proj_result = MagicMock()
        mock_proj_result.scalars.return_value.all.return_value = [mock_project]

        # Mock people query
        mock_people_result = MagicMock()
        mock_people_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[mock_proj_result, mock_people_result])

        with patch("src.context.worker.get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_entity_extract_job(job)

        # Should have added at least one entity
        assert mock_session.add.called

    @pytest.mark.asyncio
    async def test_missing_turn_is_noop(self):
        """Missing turn is silently skipped."""
        from src.context.worker import process_entity_extract_job

        job = make_job(kind="entity_extract", payload={"turn_id": str(uuid.uuid4())})

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        with patch("src.context.worker.get_session") as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await process_entity_extract_job(job)

        mock_session.add.assert_not_called()


class TestProcessPendingJobs:
    """Tests for process_pending_jobs."""

    @pytest.mark.asyncio
    async def test_processes_available_jobs(self):
        """Processes jobs until none remain."""
        from src.context.worker import process_pending_jobs

        job1 = make_job(kind="turn_summary", payload={"turn_id": str(uuid.uuid4())})
        job2 = make_job(kind="turn_summary", payload={"turn_id": str(uuid.uuid4())})

        call_count = [0]

        async def mock_claim(session, kinds=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return job1
            elif call_count[0] == 2:
                return job2
            return None

        with patch("src.context.worker.get_session") as mock_get_session, \
             patch("src.context.worker.claim_job", side_effect=mock_claim), \
             patch("src.context.worker.expire_stale_leases", new_callable=AsyncMock), \
             patch("src.context.worker._dispatch_job", new_callable=AsyncMock), \
             patch("src.context.worker.complete_job", new_callable=AsyncMock):
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await process_pending_jobs(max_jobs=5)

        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_jobs(self):
        """Returns 0 when no jobs are available."""
        from src.context.worker import process_pending_jobs

        with patch("src.context.worker.get_session") as mock_get_session, \
             patch("src.context.worker.claim_job", new_callable=AsyncMock, return_value=None), \
             patch("src.context.worker.expire_stale_leases", new_callable=AsyncMock):
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await process_pending_jobs()

        assert count == 0
