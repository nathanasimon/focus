"""Shared test fixtures."""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest


def make_email(**overrides):
    """Create a mock Email object for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "account_id": uuid.uuid4(),
        "gmail_id": f"msg-{uuid.uuid4().hex[:8]}",
        "thread_id": "thread-1",
        "sender_id": None,
        "subject": "Test Subject",
        "snippet": "This is a test email snippet.",
        "full_body": "Hello, this is the full body of the test email.",
        "classification": None,
        "urgency": None,
        "needs_reply": False,
        "reply_suggested": None,
        "reply_sent": False,
        "labels": ["INBOX"],
        "processed_at": None,
        "email_date": datetime(2026, 2, 1, 12, 0, 0),
        "raw_headers": {
            "from": "John Doe <john@example.com>",
            "to": "me@example.com",
            "subject": "Test Subject",
            "date": "Sat, 01 Feb 2026 12:00:00 +0000",
        },
        "extraction_result": None,
        "account": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_project(**overrides):
    """Create a mock Project object for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Project",
        "slug": "test-project",
        "tier": "simple",
        "status": "active",
        "description": None,
        "first_mention": datetime(2026, 1, 1),
        "last_activity": datetime(2026, 2, 1),
        "mention_count": 5,
        "source_diversity": 2,
        "people_count": 3,
        "user_pinned": False,
        "user_priority": None,
        "user_deadline": None,
        "user_deadline_note": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_task(**overrides):
    """Create a mock Task object for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "Test Task",
        "status": "backlog",
        "priority": "normal",
        "user_pinned": False,
        "user_priority": None,
        "due_date": None,
        "source_account_id": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock
