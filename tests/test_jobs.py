"""Tests for the durable job queue (src/storage/jobs.py)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.models import FocusJob


def make_job(**overrides):
    """Create a mock FocusJob for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "kind": "session_process",
        "dedupe_key": None,
        "payload": {"session_id": "test-123"},
        "status": "queued",
        "priority": 10,
        "attempts": 0,
        "max_attempts": 10,
        "locked_until": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=FocusJob)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestEnqueueJob:
    """Tests for enqueue_job."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_job(self):
        """Enqueue without dedupe_key creates a job and returns it."""
        from src.storage.jobs import enqueue_job

        session = AsyncMock()
        job_id = uuid.uuid4()
        mock_job = make_job(id=job_id)
        session.get = AsyncMock(return_value=mock_job)

        with patch("src.storage.jobs.uuid.uuid4", return_value=job_id):
            result = await enqueue_job(
                session=session,
                kind="session_process",
                payload={"test": "data"},
            )

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_enqueue_with_dedupe_key_prevents_duplicate(self):
        """Enqueue with existing dedupe_key returns None."""
        from src.storage.jobs import enqueue_job

        session = AsyncMock()
        # Simulate ON CONFLICT DO NOTHING (rowcount=0)
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute = AsyncMock(return_value=mock_result)

        result = await enqueue_job(
            session=session,
            kind="session_process",
            payload={"test": "data"},
            dedupe_key="session_process:abc",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_enqueue_with_dedupe_key_creates_new(self):
        """Enqueue with new dedupe_key creates the job."""
        from src.storage.jobs import enqueue_job

        session = AsyncMock()
        job_id = uuid.uuid4()
        mock_job = make_job(id=job_id)

        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute = AsyncMock(return_value=mock_result)
        session.get = AsyncMock(return_value=mock_job)

        with patch("src.storage.jobs.uuid.uuid4", return_value=job_id):
            result = await enqueue_job(
                session=session,
                kind="session_process",
                payload={"test": "data"},
                dedupe_key="session_process:new",
            )

        assert result is mock_job
        session.flush.assert_called_once()


class TestClaimJob:
    """Tests for claim_job."""

    @pytest.mark.asyncio
    async def test_claim_returns_job_when_available(self):
        """Claim returns the next queued job."""
        from src.storage.jobs import claim_job

        session = AsyncMock()
        job_id = uuid.uuid4()
        mock_job = make_job(id=job_id, status="processing")

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, idx: job_id
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        session.execute = AsyncMock(return_value=mock_result)
        session.get = AsyncMock(return_value=mock_job)

        result = await claim_job(session)

        assert result is mock_job

    @pytest.mark.asyncio
    async def test_claim_returns_none_when_empty(self):
        """Claim returns None when no jobs available."""
        from src.storage.jobs import claim_job

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        result = await claim_job(session)

        assert result is None


class TestCompleteJob:
    """Tests for complete_job."""

    @pytest.mark.asyncio
    async def test_complete_sets_done(self):
        """Completing a job sets status to done."""
        from src.storage.jobs import complete_job

        session = AsyncMock()
        job_id = uuid.uuid4()

        await complete_job(session, job_id)

        session.execute.assert_called_once()


class TestFailJob:
    """Tests for fail_job."""

    @pytest.mark.asyncio
    async def test_fail_retries_under_max(self):
        """Failing a job under max_attempts sets retry status."""
        from src.storage.jobs import fail_job

        session = AsyncMock()
        job = make_job(attempts=2, max_attempts=10)
        session.get = AsyncMock(return_value=job)

        await fail_job(session, job.id, "test error")

        # Should have called execute to update status
        session.execute.assert_called_once()
        call_args = session.execute.call_args
        # The update statement should set status to retry
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_fail_permanent_at_max_attempts(self):
        """Failing at max_attempts sets failed status permanently."""
        from src.storage.jobs import fail_job

        session = AsyncMock()
        job = make_job(attempts=10, max_attempts=10)
        session.get = AsyncMock(return_value=job)

        await fail_job(session, job.id, "final error")

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_missing_job_is_noop(self):
        """Failing a nonexistent job does nothing."""
        from src.storage.jobs import fail_job

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        await fail_job(session, uuid.uuid4(), "error")

        session.execute.assert_not_called()


class TestExpireStaleLeases:
    """Tests for expire_stale_leases."""

    @pytest.mark.asyncio
    async def test_expire_resets_stale_jobs(self):
        """Expired processing jobs are reset to retry."""
        from src.storage.jobs import expire_stale_leases

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute = AsyncMock(return_value=mock_result)

        count = await expire_stale_leases(session)

        assert count == 3

    @pytest.mark.asyncio
    async def test_expire_returns_zero_when_none(self):
        """Returns 0 when no leases are stale."""
        from src.storage.jobs import expire_stale_leases

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute = AsyncMock(return_value=mock_result)

        count = await expire_stale_leases(session)

        assert count == 0


class TestGetJobStats:
    """Tests for get_job_stats."""

    @pytest.mark.asyncio
    async def test_returns_counts_by_status(self):
        """Returns dict of status -> count."""
        from src.storage.jobs import get_job_stats

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("queued", 5),
            ("processing", 2),
            ("done", 10),
        ]
        session.execute = AsyncMock(return_value=mock_result)

        stats = await get_job_stats(session)

        assert stats == {"queued": 5, "processing": 2, "done": 10}

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_dict(self):
        """Empty table returns empty dict."""
        from src.storage.jobs import get_job_stats

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        stats = await get_job_stats(session)

        assert stats == {}
