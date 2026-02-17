"""Artifact extractor — parses JSONL turns for files, commands, errors, and tool calls.

Pure Python, no LLM calls. Designed for maximalist recording of everything
that happened in a conversation turn.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Artifact:
    """A single artifact extracted from a turn."""

    artifact_type: str  # file_read, file_write, file_edit, command, error, tool_call
    artifact_value: str  # The primary value (file path, command string, error message)
    artifact_metadata: dict = field(default_factory=dict)


@dataclass
class TurnArtifacts:
    """All artifacts extracted from a single turn's raw JSONL."""

    artifacts: list[Artifact] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    files_edited: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    tool_call_count: int = 0

    @property
    def files_touched(self) -> list[str]:
        """All unique files touched (read, written, edited)."""
        seen = set()
        result = []
        for f in self.files_read + self.files_written + self.files_edited:
            if f not in seen:
                seen.add(f)
                result.append(f)
        return result


# Tool name to artifact type mapping
_TOOL_TYPE_MAP = {
    "Read": "file_read",
    "Glob": "file_read",
    "Grep": "file_read",
    "Write": "file_write",
    "Edit": "file_edit",
    "NotebookEdit": "file_edit",
    "Bash": "command",
}


def extract_artifacts(raw_jsonl: str) -> TurnArtifacts:
    """Extract artifacts from a turn's raw JSONL content.

    Parses tool_use blocks to find file operations, commands, and errors.
    Parses tool_result blocks to find errors.

    Args:
        raw_jsonl: The raw JSONL string from a turn.

    Returns:
        TurnArtifacts with all extracted data.
    """
    result = TurnArtifacts()

    if not raw_jsonl:
        return result

    for line in raw_jsonl.split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        message = obj.get("message", {})
        if not isinstance(message, dict):
            continue

        content = message.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type", "")

            if block_type == "tool_use":
                _process_tool_use(block, result)
            elif block_type == "tool_result":
                _process_tool_result(block, result)

    return result


def _process_tool_use(block: dict, result: TurnArtifacts) -> None:
    """Process a tool_use block and extract artifacts.

    Args:
        block: The tool_use content block.
        result: TurnArtifacts to append to.
    """
    tool_name = block.get("name", "")
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    result.tool_call_count += 1
    artifact_type = _TOOL_TYPE_MAP.get(tool_name, "tool_call")

    if tool_name == "Read":
        path = tool_input.get("file_path", "")
        if path:
            result.files_read.append(path)
            result.artifacts.append(Artifact(
                artifact_type="file_read",
                artifact_value=path,
                artifact_metadata={"tool": tool_name},
            ))

    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        result.artifacts.append(Artifact(
            artifact_type="file_read",
            artifact_value=pattern or path,
            artifact_metadata={"tool": tool_name, "pattern": pattern, "path": path},
        ))

    elif tool_name == "Write":
        path = tool_input.get("file_path", "")
        if path:
            result.files_written.append(path)
            result.artifacts.append(Artifact(
                artifact_type="file_write",
                artifact_value=path,
                artifact_metadata={"tool": tool_name},
            ))

    elif tool_name in ("Edit", "NotebookEdit"):
        path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if path:
            result.files_edited.append(path)
            result.artifacts.append(Artifact(
                artifact_type="file_edit",
                artifact_value=path,
                artifact_metadata={
                    "tool": tool_name,
                    "old_string": (tool_input.get("old_string", "") or "")[:100],
                },
            ))

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            result.commands_run.append(command)
            result.artifacts.append(Artifact(
                artifact_type="command",
                artifact_value=command[:500],
                artifact_metadata={"tool": tool_name},
            ))

    elif tool_name == "Task":
        prompt = tool_input.get("prompt", "")[:200]
        result.artifacts.append(Artifact(
            artifact_type="tool_call",
            artifact_value=f"Task: {prompt}",
            artifact_metadata={"tool": tool_name, "subagent_type": tool_input.get("subagent_type", "")},
        ))

    else:
        # Generic tool call
        result.artifacts.append(Artifact(
            artifact_type="tool_call",
            artifact_value=tool_name,
            artifact_metadata={"tool": tool_name, "input_keys": list(tool_input.keys())[:10]},
        ))


def _process_tool_result(block: dict, result: TurnArtifacts) -> None:
    """Process a tool_result block to detect errors.

    Args:
        block: The tool_result content block.
        result: TurnArtifacts to append to.
    """
    is_error = block.get("is_error", False)
    if not is_error:
        return

    content = block.get("content", "")
    if isinstance(content, list):
        text_parts = [
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        content = "\n".join(text_parts)

    if isinstance(content, str) and content.strip():
        error_msg = content.strip()[:500]
        result.errors_encountered.append(error_msg)
        result.artifacts.append(Artifact(
            artifact_type="error",
            artifact_value=error_msg,
            artifact_metadata={},
        ))


def extract_file_paths_from_text(text: str) -> list[str]:
    """Extract file paths from free text (prompts, messages).

    Looks for common path patterns like /path/to/file or src/module/file.py.

    Args:
        text: Text to scan for file paths.

    Returns:
        List of unique file paths found.
    """
    if not text:
        return []

    # Match absolute paths and relative paths with extensions
    patterns = [
        r'(?<!\w)(/[\w./-]+\.\w+)',  # /absolute/path/file.ext
        r'(?<!\w)((?:src|tests|lib|app|pkg)/[\w./-]+\.\w+)',  # src/relative/path.ext
    ]

    paths = []
    seen = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            path = match.strip()
            if path not in seen and len(path) > 3:
                seen.add(path)
                paths.append(path)

    return paths
