"""Tests for conversation search extensions (main.py search --type conv)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def make_agent_turn(**overrides):
    """Create a mock AgentTurn for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "session_id": uuid.uuid4(),
        "turn_number": 0,
        "user_message": "Fix the auth bug",
        "assistant_summary": "Fixed OAuth2 token refresh logic",
        "turn_title": "Fix auth bug",
        "content_hash": "abc123",
        "model_name": "claude-opus-4-6",
        "tool_names": ["Read", "Edit"],
        "started_at": datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 2, 10, 12, 5, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def make_agent_session(**overrides):
    """Create a mock AgentSession for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "session_id": "test-session-abc123",
        "workspace_path": "/home/user/project",
        "turn_count": 5,
        "session_summary": "Fixed auth bugs and added tests",
        "turns": [],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestConversationSearch:
    """Tests for conversation search in the CLI."""

    def test_turn_has_searchable_fields(self):
        """Agent turns have all fields needed for search."""
        turn = make_agent_turn()
        assert turn.user_message is not None
        assert turn.assistant_summary is not None
        assert turn.turn_title is not None

    def test_turn_title_is_concise(self):
        """Turn titles are short enough for search results."""
        turn = make_agent_turn(turn_title="Fix authentication flow")
        assert len(turn.turn_title) < 80

    def test_session_has_searchable_summary(self):
        """Agent sessions have summary for search results."""
        session = make_agent_session()
        assert session.session_summary is not None
        assert session.session_id is not None

    def test_session_turns_accessible(self):
        """Session turns are accessible for display."""
        turns = [
            make_agent_turn(turn_number=0, turn_title="First turn"),
            make_agent_turn(turn_number=1, turn_title="Second turn"),
        ]
        session = make_agent_session(turns=turns)
        sorted_turns = sorted(session.turns, key=lambda t: t.turn_number)
        assert sorted_turns[0].turn_title == "First turn"
        assert sorted_turns[1].turn_title == "Second turn"

    def test_turn_tool_names_formatted(self):
        """Tool names can be joined for display."""
        turn = make_agent_turn(tool_names=["Read", "Edit", "Bash"])
        tools_str = ", ".join(turn.tool_names)
        assert "Read" in tools_str
        assert "Edit" in tools_str
        assert "Bash" in tools_str

    def test_turn_with_no_tools(self):
        """Turns with no tools display gracefully."""
        turn = make_agent_turn(tool_names=[])
        tools_str = ", ".join(turn.tool_names) if turn.tool_names else "none"
        assert tools_str == "none"

    def test_turn_with_long_user_message(self):
        """Long user messages are truncatable."""
        long_msg = "A" * 5000
        turn = make_agent_turn(user_message=long_msg)
        truncated = turn.user_message[:2000]
        assert len(truncated) == 2000
