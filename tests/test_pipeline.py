"""Tests for src/ingestion/pipeline — email processing pipeline."""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock google modules so pipeline.py can be imported without google SDK
for mod in [
    "google", "google.auth", "google.auth.transport", "google.auth.transport.requests",
    "google.oauth2", "google.oauth2.credentials", "google_auth_oauthlib",
    "google_auth_oauthlib.flow", "googleapiclient", "googleapiclient.discovery",
]:
    sys.modules.setdefault(mod, MagicMock())

from tests.conftest import make_email


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_with_emails(email_ids: list[uuid.UUID]):
    """Build a mock AsyncSession whose execute() returns the given email IDs."""
    rows = [(eid,) for eid in email_ids]
    result_mock = MagicMock()
    result_mock.all.return_value = rows

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()
    return session


def _make_inner_session(emails_by_id: dict):
    """Build a mock inner session for get_session() that can look up emails."""
    inner = AsyncMock()

    async def mock_get(model_cls, eid):
        return emails_by_id.get(eid)

    inner.get = mock_get
    inner.flush = AsyncMock()
    inner.commit = AsyncMock()
    inner.rollback = AsyncMock()

    return inner


# ---------------------------------------------------------------------------
# Tests: process_unprocessed_emails
# ---------------------------------------------------------------------------

class TestProcessUnprocessedEmails:
    """Tests for process_unprocessed_emails."""

    @pytest.mark.asyncio
    async def test_no_unprocessed_emails_returns_zeros(self):
        """When there are no unprocessed emails, return zero counts."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        from src.ingestion.pipeline import process_unprocessed_emails

        summary = await process_unprocessed_emails(session, limit=10)

        assert summary["classified"] == 0
        assert summary["deep_extracted"] == 0
        assert summary["regex_parsed"] == 0
        assert summary["skipped"] == 0
        assert summary["errors"] == 0

    @pytest.mark.asyncio
    async def test_email_classified_and_skipped(self):
        """An email classified as spam is counted as classified + skipped."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        classification = {
            "classification": "spam",
            "confidence": 0.95,
            "urgency": "low",
            "sender_type": "unknown",
            "route_to": "skip",
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification):
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["classified"] == 1
        assert summary["skipped"] == 1
        assert summary["deep_extracted"] == 0

    @pytest.mark.asyncio
    async def test_email_routed_to_deep_analysis(self):
        """A human email goes through classify → extract → resolve."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        classification = {
            "classification": "human",
            "confidence": 0.92,
            "urgency": "normal",
            "sender_type": "known",
            "route_to": "deep_analysis",
        }
        extraction = {
            "tasks": [{"text": "Review doc"}],
            "people_mentioned": ["Alice"],
            "project_links": [],
            "commitments": [],
            "reply_needed": True,
            "suggested_reply": "Will do",
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification), \
             patch("src.ingestion.pipeline.extract_and_update", new_callable=AsyncMock, return_value=extraction), \
             patch("src.ingestion.pipeline.resolve_extraction", new_callable=AsyncMock) as mock_resolve:
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["classified"] == 1
        assert summary["deep_extracted"] == 1
        mock_resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_email_routed_to_regex_parse(self):
        """An automated email goes through classify → regex parse."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        classification = {
            "classification": "automated",
            "confidence": 0.88,
            "urgency": "low",
            "sender_type": "company",
            "route_to": "regex_parse",
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification), \
             patch("src.ingestion.pipeline.parse_and_update", new_callable=AsyncMock) as mock_parse:
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["classified"] == 1
        assert summary["regex_parsed"] == 1
        mock_parse.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_in_processing_counted(self):
        """If classification raises, it's caught and counted as an error."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["errors"] == 1
        assert summary["classified"] == 0

    @pytest.mark.asyncio
    async def test_missing_email_counted_as_error(self):
        """If the email is gone by the time the inner session fetches it, count as error."""
        email_id = uuid.uuid4()
        session = _make_session_with_emails([email_id])

        # Inner session returns None for this email
        inner_session = _make_inner_session({})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx):
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["errors"] == 1

    @pytest.mark.asyncio
    async def test_multiple_emails_each_get_own_session(self):
        """Regression: each email must get its own session (not shared)."""
        ids = [uuid.uuid4() for _ in range(3)]
        emails = {eid: make_email(id=eid, classification=None) for eid in ids}
        session = _make_session_with_emails(ids)

        sessions_created = []

        def mock_get_session():
            inner = _make_inner_session(emails)
            sessions_created.append(inner)
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=inner)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        classification = {
            "classification": "spam",
            "confidence": 0.9,
            "urgency": "low",
            "sender_type": "unknown",
            "route_to": "skip",
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", side_effect=mock_get_session), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification):
            summary = await process_unprocessed_emails(session, limit=10)

        # Each email should have gotten its own session
        assert len(sessions_created) == 3
        assert summary["classified"] == 3

    @pytest.mark.asyncio
    async def test_deep_analysis_skips_resolve_when_no_entities(self):
        """If extraction has no tasks/people/projects, resolve is not called."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        classification = {
            "classification": "human",
            "confidence": 0.85,
            "urgency": "normal",
            "sender_type": "known",
            "route_to": "deep_analysis",
        }
        extraction = {
            "tasks": [],
            "people_mentioned": [],
            "project_links": [],
            "commitments": [],
            "reply_needed": False,
            "suggested_reply": None,
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification), \
             patch("src.ingestion.pipeline.extract_and_update", new_callable=AsyncMock, return_value=extraction), \
             patch("src.ingestion.pipeline.resolve_extraction", new_callable=AsyncMock) as mock_resolve:
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["deep_extracted"] == 1
        mock_resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_commitments_only_triggers_resolve(self):
        """Regression P-006: extraction with commitments but no tasks/people must still call resolve."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        inner_session = _make_inner_session({email_id: email})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        classification = {
            "classification": "human",
            "confidence": 0.90,
            "urgency": "normal",
            "sender_type": "known",
            "route_to": "deep_analysis",
        }
        extraction = {
            "tasks": [],
            "commitments": [{"text": "I'll send the report by Friday", "by": "sender"}],
            "people_mentioned": [],
            "project_links": [],
            "reply_needed": False,
            "suggested_reply": None,
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", return_value=mock_ctx), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification), \
             patch("src.ingestion.pipeline.extract_and_update", new_callable=AsyncMock, return_value=extraction), \
             patch("src.ingestion.pipeline.resolve_extraction", new_callable=AsyncMock) as mock_resolve:
            summary = await process_unprocessed_emails(session, limit=10)

        assert summary["deep_extracted"] == 1
        mock_resolve.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_outer_session_committed_before_inner_sessions(self):
        """Regression: outer session must commit so inner sessions can see the emails."""
        email_id = uuid.uuid4()
        email = make_email(id=email_id, classification=None)
        session = _make_session_with_emails([email_id])

        call_order = []

        original_commit = session.commit

        async def tracking_commit():
            call_order.append("commit")
            return await original_commit()

        session.commit = tracking_commit

        inner_session = _make_inner_session({email_id: email})

        def mock_get_session():
            call_order.append("get_session")
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=inner_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        classification = {
            "classification": "spam",
            "confidence": 0.9,
            "urgency": "low",
            "sender_type": "unknown",
            "route_to": "skip",
        }

        from src.ingestion.pipeline import process_unprocessed_emails

        with patch("src.ingestion.pipeline.get_session", side_effect=mock_get_session), \
             patch("src.ingestion.pipeline.classify_and_update", new_callable=AsyncMock, return_value=classification):
            summary = await process_unprocessed_emails(session, limit=10)

        # Commit must happen before any inner session is created
        assert "commit" in call_order
        assert "get_session" in call_order
        assert call_order.index("commit") < call_order.index("get_session")
