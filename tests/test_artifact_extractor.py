"""Tests for the artifact extractor (src/context/artifact_extractor.py)."""

import json

import pytest

from src.context.artifact_extractor import (
    Artifact,
    TurnArtifacts,
    extract_artifacts,
    extract_file_paths_from_text,
)


def _make_jsonl(*messages) -> str:
    """Build raw JSONL from message dicts."""
    lines = []
    for msg in messages:
        lines.append(json.dumps(msg))
    return "\n".join(lines)


def _tool_use_msg(tool_name: str, tool_input: dict, tool_use_id: str = "tu_1") -> dict:
    """Build an assistant message with a tool_use block."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        },
    }


def _tool_result_msg(tool_use_id: str = "tu_1", content: str = "", is_error: bool = False) -> dict:
    """Build a user message with a tool_result block."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
    }


class TestExtractArtifactsRead:
    """Tests for extracting Read tool artifacts."""

    def test_read_extracts_file_path(self):
        raw = _make_jsonl(_tool_use_msg("Read", {"file_path": "/home/user/src/main.py"}))
        result = extract_artifacts(raw)
        assert result.files_read == ["/home/user/src/main.py"]
        assert result.tool_call_count == 1

    def test_read_creates_artifact(self):
        raw = _make_jsonl(_tool_use_msg("Read", {"file_path": "/path/to/file.py"}))
        result = extract_artifacts(raw)
        assert len(result.artifacts) == 1
        assert result.artifacts[0].artifact_type == "file_read"
        assert result.artifacts[0].artifact_value == "/path/to/file.py"

    def test_read_empty_path_skipped(self):
        raw = _make_jsonl(_tool_use_msg("Read", {"file_path": ""}))
        result = extract_artifacts(raw)
        assert result.files_read == []
        assert result.tool_call_count == 1


class TestExtractArtifactsWrite:
    """Tests for extracting Write tool artifacts."""

    def test_write_extracts_file_path(self):
        raw = _make_jsonl(_tool_use_msg("Write", {"file_path": "/home/user/new_file.py", "content": "hello"}))
        result = extract_artifacts(raw)
        assert result.files_written == ["/home/user/new_file.py"]

    def test_write_artifact_type(self):
        raw = _make_jsonl(_tool_use_msg("Write", {"file_path": "/path/to/file.py", "content": "x"}))
        result = extract_artifacts(raw)
        assert result.artifacts[0].artifact_type == "file_write"


class TestExtractArtifactsEdit:
    """Tests for extracting Edit tool artifacts."""

    def test_edit_extracts_file_path(self):
        raw = _make_jsonl(_tool_use_msg("Edit", {
            "file_path": "/home/user/src/main.py",
            "old_string": "old",
            "new_string": "new",
        }))
        result = extract_artifacts(raw)
        assert result.files_edited == ["/home/user/src/main.py"]

    def test_edit_artifact_has_old_string_preview(self):
        raw = _make_jsonl(_tool_use_msg("Edit", {
            "file_path": "/path/to/file.py",
            "old_string": "some old content here",
            "new_string": "new content",
        }))
        result = extract_artifacts(raw)
        assert "old_string" in result.artifacts[0].artifact_metadata

    def test_notebook_edit_extracts_path(self):
        raw = _make_jsonl(_tool_use_msg("NotebookEdit", {
            "notebook_path": "/home/user/notebook.ipynb",
            "new_source": "print('hi')",
        }))
        result = extract_artifacts(raw)
        assert result.files_edited == ["/home/user/notebook.ipynb"]


class TestExtractArtifactsBash:
    """Tests for extracting Bash tool artifacts."""

    def test_bash_extracts_command(self):
        raw = _make_jsonl(_tool_use_msg("Bash", {"command": "pytest tests/ -x -q"}))
        result = extract_artifacts(raw)
        assert result.commands_run == ["pytest tests/ -x -q"]

    def test_bash_long_command_truncated(self):
        long_cmd = "x" * 600
        raw = _make_jsonl(_tool_use_msg("Bash", {"command": long_cmd}))
        result = extract_artifacts(raw)
        assert len(result.artifacts[0].artifact_value) <= 500


class TestExtractArtifactsSearch:
    """Tests for extracting Glob/Grep tool artifacts."""

    def test_glob_extracts_pattern(self):
        raw = _make_jsonl(_tool_use_msg("Glob", {"pattern": "**/*.py"}))
        result = extract_artifacts(raw)
        assert result.artifacts[0].artifact_type == "file_read"
        assert result.artifacts[0].artifact_value == "**/*.py"

    def test_grep_extracts_pattern(self):
        raw = _make_jsonl(_tool_use_msg("Grep", {"pattern": "def foo", "path": "/home/user/src"}))
        result = extract_artifacts(raw)
        assert result.artifacts[0].artifact_metadata["pattern"] == "def foo"


class TestExtractArtifactsErrors:
    """Tests for extracting errors from tool results."""

    def test_error_tool_result_extracted(self):
        raw = _make_jsonl(
            _tool_use_msg("Bash", {"command": "false"}),
            _tool_result_msg(content="command failed with exit code 1", is_error=True),
        )
        result = extract_artifacts(raw)
        assert len(result.errors_encountered) == 1
        assert "command failed" in result.errors_encountered[0]

    def test_non_error_result_ignored(self):
        raw = _make_jsonl(
            _tool_use_msg("Bash", {"command": "true"}),
            _tool_result_msg(content="success", is_error=False),
        )
        result = extract_artifacts(raw)
        assert result.errors_encountered == []

    def test_error_with_list_content(self):
        raw = _make_jsonl({
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "is_error": True,
                        "content": [{"type": "text", "text": "File not found"}],
                    }
                ],
            },
        })
        result = extract_artifacts(raw)
        assert "File not found" in result.errors_encountered[0]

    def test_error_long_message_truncated(self):
        long_error = "E" * 600
        raw = _make_jsonl(
            _tool_result_msg(content=long_error, is_error=True),
        )
        result = extract_artifacts(raw)
        assert len(result.errors_encountered[0]) <= 500


class TestExtractArtifactsGenericTools:
    """Tests for extracting generic/unknown tool calls."""

    def test_task_tool_extracted(self):
        raw = _make_jsonl(_tool_use_msg("Task", {
            "prompt": "Search for all Python files",
            "subagent_type": "Explore",
        }))
        result = extract_artifacts(raw)
        assert result.artifacts[0].artifact_type == "tool_call"
        assert "Task:" in result.artifacts[0].artifact_value

    def test_unknown_tool_extracted(self):
        raw = _make_jsonl(_tool_use_msg("CustomTool", {"arg1": "val1"}))
        result = extract_artifacts(raw)
        assert result.artifacts[0].artifact_type == "tool_call"
        assert result.artifacts[0].artifact_value == "CustomTool"


class TestExtractArtifactsMultiple:
    """Tests for multiple artifacts in a single turn."""

    def test_multiple_tools_counted(self):
        raw = _make_jsonl(
            _tool_use_msg("Read", {"file_path": "/a.py"}, "tu_1"),
            _tool_use_msg("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"}, "tu_2"),
            _tool_use_msg("Bash", {"command": "pytest"}, "tu_3"),
        )
        result = extract_artifacts(raw)
        assert result.tool_call_count == 3
        assert len(result.files_read) == 1
        assert len(result.files_edited) == 1
        assert len(result.commands_run) == 1

    def test_files_touched_deduplicates(self):
        raw = _make_jsonl(
            _tool_use_msg("Read", {"file_path": "/a.py"}, "tu_1"),
            _tool_use_msg("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"}, "tu_2"),
        )
        result = extract_artifacts(raw)
        assert result.files_touched == ["/a.py"]


class TestExtractArtifactsEdgeCases:
    """Edge case tests."""

    def test_empty_input(self):
        result = extract_artifacts("")
        assert result.tool_call_count == 0
        assert result.artifacts == []

    def test_invalid_json_lines_skipped(self):
        raw = "not json\n{\"type\": \"assistant\", \"message\": {\"role\": \"assistant\", \"content\": [{\"type\": \"tool_use\", \"name\": \"Read\", \"id\": \"1\", \"input\": {\"file_path\": \"/a.py\"}}]}}"
        result = extract_artifacts(raw)
        assert len(result.files_read) == 1

    def test_non_list_content_ignored(self):
        raw = _make_jsonl({
            "type": "assistant",
            "message": {"role": "assistant", "content": "just a string"},
        })
        result = extract_artifacts(raw)
        assert result.tool_call_count == 0

    def test_missing_message_key(self):
        raw = _make_jsonl({"type": "assistant"})
        result = extract_artifacts(raw)
        assert result.tool_call_count == 0

    def test_tool_use_with_non_dict_input(self):
        raw = _make_jsonl({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "id": "1", "input": "not a dict"}
                ],
            },
        })
        result = extract_artifacts(raw)
        # Should still count but not crash
        assert result.tool_call_count == 1


class TestExtractFilePathsFromText:
    """Tests for extract_file_paths_from_text."""

    def test_absolute_path(self):
        paths = extract_file_paths_from_text("look at /home/user/src/main.py")
        assert "/home/user/src/main.py" in paths

    def test_relative_src_path(self):
        paths = extract_file_paths_from_text("check src/context/worker.py")
        assert "src/context/worker.py" in paths

    def test_tests_path(self):
        paths = extract_file_paths_from_text("run tests/test_main.py")
        assert "tests/test_main.py" in paths

    def test_no_paths_in_plain_text(self):
        paths = extract_file_paths_from_text("hello world, no paths here")
        assert paths == []

    def test_empty_text(self):
        assert extract_file_paths_from_text("") == []

    def test_none_text(self):
        assert extract_file_paths_from_text(None) == []

    def test_deduplicates(self):
        paths = extract_file_paths_from_text("see /home/user/a.py and also /home/user/a.py")
        assert len(paths) == 1

    def test_multiple_paths(self):
        paths = extract_file_paths_from_text("compare /a/b.py with src/c/d.py")
        assert len(paths) == 2
