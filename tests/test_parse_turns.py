"""Tests for JSONL turn parsing (parse_session_into_turns in claude_code.py)."""

import json
import tempfile
from pathlib import Path

import pytest

from src.ingestion.claude_code import (
    _extract_tool_names,
    compute_content_hash,
    parse_session_into_turns,
)


def _write_jsonl(lines: list[dict]) -> Path:
    """Write JSONL lines to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        f.write(json.dumps(line) + "\n")
    f.close()
    return Path(f.name)


def _msg(role: str, content: str, **kwargs):
    """Build a JSONL message dict."""
    obj = {
        "type": role,
        "message": {"role": role, "content": content},
        "timestamp": kwargs.get("timestamp", "2026-02-10T12:00:00Z"),
        "sessionId": kwargs.get("session_id", "test-session"),
    }
    obj.update({k: v for k, v in kwargs.items() if k not in ("timestamp", "session_id")})
    return obj


class TestComputeContentHash:
    """Tests for compute_content_hash."""

    def test_deterministic(self):
        """Same input produces same hash."""
        assert compute_content_hash("hello") == compute_content_hash("hello")

    def test_different_input_different_hash(self):
        """Different inputs produce different hashes."""
        assert compute_content_hash("hello") != compute_content_hash("world")

    def test_returns_hex_string(self):
        """Returns a valid hex digest string."""
        result = compute_content_hash("test")
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex digest length
        int(result, 16)  # Should be valid hex


class TestExtractToolNames:
    """Tests for _extract_tool_names."""

    def test_extracts_tool_use_blocks(self):
        """Extracts tool names from content blocks."""
        content = [
            {"type": "text", "text": "Let me read that file."},
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Edit", "input": {}},
        ]
        assert _extract_tool_names(content) == ["Read", "Edit"]

    def test_deduplicates_tool_names(self):
        """Same tool used twice appears only once."""
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Read", "input": {}},
        ]
        assert _extract_tool_names(content) == ["Read"]

    def test_string_content_returns_empty(self):
        """String content (user messages) returns empty list."""
        assert _extract_tool_names("Hello") == []

    def test_empty_list_returns_empty(self):
        """Empty content list returns empty."""
        assert _extract_tool_names([]) == []


class TestParseSessionIntoTurns:
    """Tests for parse_session_into_turns."""

    def test_basic_turn_grouping(self):
        """User + assistant messages are grouped into one turn."""
        path = _write_jsonl([
            _msg("user", "Fix the bug"),
            _msg("assistant", [{"type": "text", "text": "I'll fix that."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert turns[0]["turn_number"] == 0
        assert turns[0]["user_message"] == "Fix the bug"
        assert "I'll fix that." in turns[0]["assistant_text"]

    def test_multiple_turns(self):
        """Multiple user+assistant exchanges create multiple turns."""
        path = _write_jsonl([
            _msg("user", "First question"),
            _msg("assistant", [{"type": "text", "text": "First answer."}]),
            _msg("user", "Second question"),
            _msg("assistant", [{"type": "text", "text": "Second answer."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 2
        assert turns[0]["turn_number"] == 0
        assert turns[0]["user_message"] == "First question"
        assert turns[1]["turn_number"] == 1
        assert turns[1]["user_message"] == "Second question"

    def test_tool_names_extracted(self):
        """Tool use blocks are captured in tool_names."""
        path = _write_jsonl([
            _msg("user", "Read the config file"),
            _msg("assistant", [
                {"type": "text", "text": "Reading..."},
                {"type": "tool_use", "name": "Read", "input": {"path": "/config.py"}},
            ]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert "Read" in turns[0]["tool_names"]

    def test_content_hash_deterministic(self):
        """Same file parsed twice produces same content hashes."""
        messages = [
            _msg("user", "Hello"),
            _msg("assistant", [{"type": "text", "text": "Hi there."}]),
        ]
        path = _write_jsonl(messages)

        turns1 = parse_session_into_turns(path)
        turns2 = parse_session_into_turns(path)

        assert turns1[0]["content_hash"] == turns2[0]["content_hash"]

    def test_sidechain_filtered(self):
        """Messages with isSidechain=True are excluded."""
        path = _write_jsonl([
            _msg("user", "Main question"),
            {**_msg("assistant", [{"type": "text", "text": "Subagent work"}]), "isSidechain": True},
            _msg("assistant", [{"type": "text", "text": "Main answer."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert "Main answer." in turns[0]["assistant_text"]
        assert "Subagent" not in turns[0]["assistant_text"]

    def test_meta_messages_filtered(self):
        """Messages with isMeta=True are excluded."""
        path = _write_jsonl([
            _msg("user", "Real question"),
            {**_msg("user", "meta stuff"), "isMeta": True},
            _msg("assistant", [{"type": "text", "text": "Real answer."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert turns[0]["user_message"] == "Real question"

    def test_empty_file_returns_empty(self):
        """Empty file returns empty list."""
        path = _write_jsonl([])
        turns = parse_session_into_turns(path)

        assert turns == []

    def test_nonexistent_file_returns_empty(self):
        """Nonexistent file returns empty list."""
        turns = parse_session_into_turns(Path("/nonexistent/file.jsonl"))

        assert turns == []

    def test_command_messages_skipped(self):
        """Messages starting with <command-name> are filtered."""
        path = _write_jsonl([
            _msg("user", "<command-name>help</command-name>"),
            _msg("user", "Real question"),
            _msg("assistant", [{"type": "text", "text": "Answer."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert turns[0]["user_message"] == "Real question"

    def test_multiple_assistant_messages_in_one_turn(self):
        """Multiple assistant messages before next user are merged."""
        path = _write_jsonl([
            _msg("user", "Complex request"),
            _msg("assistant", [{"type": "text", "text": "Part 1."}]),
            _msg("assistant", [{"type": "text", "text": "Part 2."}]),
        ])
        turns = parse_session_into_turns(path)

        assert len(turns) == 1
        assert "Part 1." in turns[0]["assistant_text"]
        assert "Part 2." in turns[0]["assistant_text"]

    def test_raw_jsonl_contains_all_lines(self):
        """raw_jsonl field contains all original JSONL lines for the turn."""
        path = _write_jsonl([
            _msg("user", "Question"),
            _msg("assistant", [{"type": "text", "text": "Answer."}]),
        ])
        turns = parse_session_into_turns(path)

        # raw_jsonl should contain both lines
        lines = turns[0]["raw_jsonl"].split("\n")
        assert len(lines) == 2
        # Each line should be valid JSON
        for line in lines:
            json.loads(line)
