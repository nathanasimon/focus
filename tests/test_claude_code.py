"""Tests for Claude Code session capture — parsing and decision extraction."""

import json
import tempfile
from pathlib import Path

import pytest

from src.ingestion.claude_code import (
    _extract_text_content,
    _parse_decisions,
    _parse_timestamp,
    build_session_summary,
    get_session_metadata,
    parse_session_file,
)


# --- Text content extraction ---


class TestExtractTextContent:
    def test_string_content(self):
        assert _extract_text_content("Hello world") == "Hello world"

    def test_empty_string(self):
        assert _extract_text_content("") == ""

    def test_list_with_text_blocks(self):
        content = [
            {"type": "text", "text": "First paragraph"},
            {"type": "text", "text": "Second paragraph"},
        ]
        assert _extract_text_content(content) == "First paragraph\nSecond paragraph"

    def test_list_filters_non_text_blocks(self):
        content = [
            {"type": "text", "text": "Some text"},
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "text", "text": "More text"},
        ]
        result = _extract_text_content(content)
        assert result == "Some text\nMore text"

    def test_list_with_no_text_blocks(self):
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_result", "content": "file contents"},
        ]
        assert _extract_text_content(content) == ""

    def test_none_content(self):
        assert _extract_text_content(None) == ""

    def test_int_content(self):
        assert _extract_text_content(42) == ""

    def test_empty_list(self):
        assert _extract_text_content([]) == ""

    def test_block_without_type(self):
        content = [{"text": "no type field"}]
        assert _extract_text_content(content) == ""

    def test_block_without_text(self):
        content = [{"type": "text"}]
        assert _extract_text_content(content) == ""


# --- Decision parsing ---


class TestParseDecisions:
    def test_valid_json_array(self):
        raw = json.dumps([
            {"decision": "Use SQLAlchemy 2.0", "context": "Modern async support", "trade_off": "Learning curve"},
        ])
        result = _parse_decisions(raw)
        assert len(result) == 1
        assert result[0]["decision"] == "Use SQLAlchemy 2.0"
        assert result[0]["context"] == "Modern async support"

    def test_empty_array(self):
        assert _parse_decisions("[]") == []

    def test_with_markdown_fences(self):
        raw = "```json\n[{\"decision\": \"Use Pydantic\"}]\n```"
        result = _parse_decisions(raw)
        assert len(result) == 1
        assert result[0]["decision"] == "Use Pydantic"

    def test_with_surrounding_text(self):
        raw = "Here are the decisions:\n[{\"decision\": \"Use FastAPI\"}]\nEnd of decisions."
        result = _parse_decisions(raw)
        assert len(result) == 1

    def test_invalid_json(self):
        assert _parse_decisions("not json at all") == []

    def test_json_not_array(self):
        assert _parse_decisions('{"decision": "something"}') == []

    def test_missing_decision_field(self):
        raw = json.dumps([{"context": "no decision field"}])
        result = _parse_decisions(raw)
        assert result == []

    def test_filters_invalid_entries(self):
        raw = json.dumps([
            {"decision": "Valid decision"},
            {"context": "Missing decision field"},
            "not a dict",
            {"decision": "Another valid one"},
        ])
        result = _parse_decisions(raw)
        assert len(result) == 2

    def test_defaults_optional_fields(self):
        raw = json.dumps([{"decision": "Minimal decision"}])
        result = _parse_decisions(raw)
        assert result[0]["context"] == ""
        assert result[0]["trade_off"] == ""
        assert result[0]["date"] is None
        assert result[0]["tags"] == []

    def test_preserves_tags(self):
        raw = json.dumps([{"decision": "Use async", "tags": ["architecture", "python"]}])
        result = _parse_decisions(raw)
        assert result[0]["tags"] == ["architecture", "python"]

    def test_markdown_fence_with_language(self):
        raw = "```json\n[{\"decision\": \"Test\"}]\n```"
        result = _parse_decisions(raw)
        assert len(result) == 1

    def test_triple_backtick_on_same_line(self):
        raw = "```[{\"decision\": \"Test\"}]```"
        result = _parse_decisions(raw)
        assert len(result) == 1


# --- Timestamp parsing ---


class TestParseTimestamp:
    def test_iso_format(self):
        result = _parse_timestamp("2025-01-15T10:30:00+00:00")
        assert result is not None
        assert result.year == 2025
        assert result.month == 1

    def test_z_suffix(self):
        result = _parse_timestamp("2025-01-15T10:30:00Z")
        assert result is not None

    def test_none_input(self):
        assert _parse_timestamp(None) is None

    def test_empty_string(self):
        assert _parse_timestamp("") is None

    def test_invalid_format(self):
        assert _parse_timestamp("not-a-date") is None


# --- Session file parsing ---


class TestParseSessionFile:
    def _write_session(self, lines: list[dict]) -> Path:
        """Write JSONL session data to a temp file."""
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        for line in lines:
            tmp.write(json.dumps(line) + "\n")
        tmp.close()
        return Path(tmp.name)

    def test_basic_conversation(self):
        path = self._write_session([
            {
                "type": "user",
                "timestamp": "2025-01-15T10:00:00Z",
                "sessionId": "abc123",
                "message": {"role": "user", "content": "Help me build a feature for this project"},
            },
            {
                "type": "assistant",
                "timestamp": "2025-01-15T10:00:05Z",
                "sessionId": "abc123",
                "message": {"role": "assistant", "content": [
                    {"type": "text", "text": "I'll help you build that feature. Let me start by reading the code."},
                ]},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"
        Path(path).unlink()

    def test_filters_sidechain(self):
        path = self._write_session([
            {
                "type": "assistant",
                "isSidechain": True,
                "message": {"role": "assistant", "content": "Subagent work here"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 0
        Path(path).unlink()

    def test_filters_meta_messages(self):
        path = self._write_session([
            {
                "type": "user",
                "isMeta": True,
                "message": {"role": "user", "content": "System configuration message that is long enough"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 0
        Path(path).unlink()

    def test_filters_short_content(self):
        path = self._write_session([
            {
                "type": "user",
                "message": {"role": "user", "content": "ok"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 0  # "ok" is < 10 chars
        Path(path).unlink()

    def test_filters_command_messages(self):
        path = self._write_session([
            {
                "type": "user",
                "message": {"role": "user", "content": "<command-name>clear</command-name>"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 0
        Path(path).unlink()

    def test_filters_local_command(self):
        path = self._write_session([
            {
                "type": "user",
                "message": {"role": "user", "content": "<local-command name='help'>something or other here</local-command>"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 0
        Path(path).unlink()

    def test_skips_non_user_assistant_types(self):
        path = self._write_session([
            {"type": "system", "message": {"content": "System startup message that is long enough"}},
            {"type": "progress", "message": {"content": "Loading something that is long enough here"}},
            {
                "type": "user",
                "message": {"role": "user", "content": "An actual user message that should pass"},
            },
        ])
        turns = parse_session_file(path)
        assert len(turns) == 1
        Path(path).unlink()

    def test_handles_malformed_json_lines(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        tmp.write('{"type": "user", "message": {"role": "user", "content": "Valid message that is long enough"}}\n')
        tmp.write("not valid json at all\n")
        tmp.write('{"type": "user", "message": {"role": "user", "content": "Another valid message here too"}}\n')
        tmp.close()
        turns = parse_session_file(Path(tmp.name))
        assert len(turns) == 2
        Path(tmp.name).unlink()

    def test_empty_file(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        tmp.close()
        turns = parse_session_file(Path(tmp.name))
        assert turns == []
        Path(tmp.name).unlink()

    def test_preserves_session_id(self):
        path = self._write_session([
            {
                "type": "user",
                "sessionId": "session-uuid-123",
                "message": {"role": "user", "content": "Long enough message here for testing purposes"},
            },
        ])
        turns = parse_session_file(path)
        assert turns[0]["session_id"] == "session-uuid-123"
        Path(path).unlink()


# --- Session summary ---


class TestBuildSessionSummary:
    def test_basic_summary(self):
        turns = [
            {"role": "user", "content": "Build a feature"},
            {"role": "assistant", "content": "I'll help with that"},
        ]
        summary = build_session_summary(turns)
        assert "[USER]: Build a feature" in summary
        assert "[ASSISTANT]: I'll help with that" in summary

    def test_truncates_long_messages(self):
        turns = [{"role": "user", "content": "x" * 2000}]
        summary = build_session_summary(turns)
        assert len(summary) < 2000
        assert "..." in summary

    def test_respects_max_chars(self):
        turns = [{"role": "user", "content": "Short message"} for _ in range(100)]
        summary = build_session_summary(turns, max_chars=200)
        assert len(summary) <= 250  # Allow some margin for the last entry

    def test_empty_turns(self):
        assert build_session_summary([]) == ""


# --- Session metadata ---


class TestGetSessionMetadata:
    def test_basic_metadata(self):
        path = Path("/home/user/.claude/projects/-home-user-myproject/abc123.jsonl")
        turns = [
            {"role": "user", "content": "Hello", "timestamp": "2025-01-15T10:00:00Z"},
            {"role": "assistant", "content": "Hi", "timestamp": "2025-01-15T10:05:00Z"},
        ]
        meta = get_session_metadata(path, turns)
        assert meta["session_id"] == "abc123"
        assert meta["project_dir"] == "-home-user-myproject"
        assert meta["turn_count"] == 2
        assert meta["user_turns"] == 1
        assert meta["assistant_turns"] == 1
        assert meta["start_time"] == "2025-01-15T10:00:00Z"
        assert meta["end_time"] == "2025-01-15T10:05:00Z"

    def test_no_timestamps(self):
        path = Path("/tmp/session.jsonl")
        turns = [{"role": "user", "content": "Hi"}]
        meta = get_session_metadata(path, turns)
        assert meta["start_time"] is None
        assert meta["end_time"] is None

    def test_empty_turns(self):
        path = Path("/tmp/session.jsonl")
        meta = get_session_metadata(path, [])
        assert meta["turn_count"] == 0
        assert meta["user_turns"] == 0
        assert meta["assistant_turns"] == 0
