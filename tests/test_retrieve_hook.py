"""Tests for the retrieve hook CLI (src/cli/retrieve_cmd.py)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHookRetrieve:
    """Tests for the _hook_retrieve function."""

    def test_empty_stdin_exits_zero(self):
        """Empty stdin causes clean exit."""
        from src.cli.retrieve_cmd import _hook_retrieve

        with patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = ""
            _hook_retrieve()

        assert exc_info.value.code == 0

    def test_invalid_json_exits_zero(self):
        """Invalid JSON input causes clean exit."""
        from src.cli.retrieve_cmd import _hook_retrieve

        with patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = "not json"
            _hook_retrieve()

        assert exc_info.value.code == 0

    def test_no_prompt_exits_zero(self):
        """Input without prompt field causes clean exit."""
        from src.cli.retrieve_cmd import _hook_retrieve

        with patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = json.dumps({"session_id": "test"})
            _hook_retrieve()

        assert exc_info.value.code == 0

    def test_outputs_valid_json_with_context(self):
        """When context is available, outputs valid hook JSON."""
        from src.cli.retrieve_cmd import _hook_retrieve

        input_data = json.dumps({
            "prompt": "Fix the bug",
            "session_id": "test",
            "cwd": "/home/user/project",
        })

        captured_output = []

        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.print", side_effect=captured_output.append), \
             patch("asyncio.run") as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = input_data
            mock_run.return_value = "## Focus Context\n\n[Task] Fix the thing"
            _hook_retrieve()

        assert exc_info.value.code == 0

        # Should have printed valid JSON
        if captured_output:
            output = json.loads(captured_output[0])
            assert "hookSpecificOutput" in output
            assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
            assert "additionalContext" in output["hookSpecificOutput"]

    def test_no_context_outputs_nothing(self):
        """When no context is relevant, outputs nothing."""
        from src.cli.retrieve_cmd import _hook_retrieve

        input_data = json.dumps({
            "prompt": "hi",
            "session_id": "test",
            "cwd": "/home/user/project",
        })

        captured_output = []

        with patch("sys.stdin") as mock_stdin, \
             patch("builtins.print", side_effect=captured_output.append), \
             patch("asyncio.run") as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = input_data
            mock_run.return_value = ""
            _hook_retrieve()

        assert exc_info.value.code == 0
        assert len(captured_output) == 0


class TestHookRecordCli:
    """Tests for the record hook path."""

    def test_empty_stdin_exits_zero(self):
        """Empty stdin causes clean exit."""
        from src.cli.record_cmd import _hook_record

        with patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = ""
            _hook_record()

        assert exc_info.value.code == 0

    def test_missing_session_id_exits_zero(self):
        """Missing session_id causes clean exit."""
        from src.cli.record_cmd import _hook_record

        with patch("sys.stdin") as mock_stdin, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = json.dumps({"cwd": "/tmp"})
            _hook_record()

        assert exc_info.value.code == 0

    def test_valid_input_enqueues(self):
        """Valid input calls enqueue_session_recording."""
        from src.cli.record_cmd import _hook_record

        input_data = json.dumps({
            "session_id": "sess-123",
            "transcript_path": "/path/to.jsonl",
            "cwd": "/home/user/project",
        })

        with patch("sys.stdin") as mock_stdin, \
             patch("asyncio.run") as mock_run, \
             pytest.raises(SystemExit) as exc_info:
            mock_stdin.read.return_value = input_data
            _hook_record()

        assert exc_info.value.code == 0
        mock_run.assert_called_once()
