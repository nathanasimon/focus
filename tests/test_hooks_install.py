"""Tests for hook installation (src/cli/hooks_cmd.py).

Note: More comprehensive tests are in test_hooks_cmd.py. This file
tests the install/uninstall logic at a slightly higher level.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli.hooks_cmd import (
    _has_focus_hook,
    _read_settings,
    _remove_focus_hooks,
    _write_settings,
    get_focus_hooks,
)


class TestHasFocusHook:
    """Tests for _has_focus_hook."""

    def test_detects_focus_hook(self):
        entries = [
            {"hooks": [{"type": "command", "command": "focus retrieve --hook"}]}
        ]
        assert _has_focus_hook(entries) is True

    def test_ignores_non_focus_hooks(self):
        entries = [
            {"hooks": [{"type": "command", "command": "other-tool do-thing"}]}
        ]
        assert _has_focus_hook(entries) is False

    def test_empty_list(self):
        assert _has_focus_hook([]) is False

    def test_mixed_hooks(self):
        entries = [
            {"hooks": [{"type": "command", "command": "other-tool thing"}]},
            {"hooks": [{"type": "command", "command": "focus record --hook"}]},
        ]
        assert _has_focus_hook(entries) is True


class TestRemoveFocusHooks:
    """Tests for _remove_focus_hooks."""

    def test_removes_focus_only(self):
        entries = [
            {"hooks": [{"type": "command", "command": "focus retrieve --hook"}]},
            {"hooks": [{"type": "command", "command": "other-tool thing"}]},
        ]
        result = _remove_focus_hooks(entries)

        assert len(result) == 1
        assert result[0]["hooks"][0]["command"] == "other-tool thing"

    def test_removes_all_when_only_focus(self):
        entries = [
            {"hooks": [{"type": "command", "command": "focus record --hook"}]},
        ]
        result = _remove_focus_hooks(entries)

        assert result == []

    def test_preserves_non_focus_in_mixed_entry(self):
        entries = [
            {"hooks": [
                {"type": "command", "command": "focus record --hook"},
                {"type": "command", "command": "other-tool thing"},
            ]},
        ]
        result = _remove_focus_hooks(entries)

        assert len(result) == 1
        assert len(result[0]["hooks"]) == 1
        assert result[0]["hooks"][0]["command"] == "other-tool thing"


class TestInstallHooks:
    """Tests for install_hooks (integration-style)."""

    def test_creates_settings_file(self, tmp_path):
        """When no settings.json exists, creates one with Focus hooks."""
        settings_path = tmp_path / "settings.json"

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
                focus_hooks = get_focus_hooks()
                settings = {"hooks": {}}
                for event_name, focus_entry in focus_hooks.items():
                    settings["hooks"][event_name] = [focus_entry]
                _write_settings(settings)

        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "UserPromptSubmit" in data["hooks"]
        assert "Stop" in data["hooks"]

    def test_preserves_existing_hooks(self, tmp_path):
        """Existing non-Focus hooks are preserved."""
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "other-tool analyze"}]}
                ]
            }
        }
        settings_path.write_text(json.dumps(existing))

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
                settings = _read_settings()
                hooks = settings.get("hooks", {})
                focus_hooks = get_focus_hooks()

                for event_name, focus_entry in focus_hooks.items():
                    entries = hooks.get(event_name, [])
                    if not _has_focus_hook(entries):
                        entries.append(focus_entry)
                        hooks[event_name] = entries

                settings["hooks"] = hooks
                _write_settings(settings)

        data = json.loads(settings_path.read_text())
        user_prompt_hooks = data["hooks"]["UserPromptSubmit"]
        assert len(user_prompt_hooks) == 2
        commands = [
            h["command"]
            for entry in user_prompt_hooks
            for h in entry.get("hooks", [])
        ]
        assert "other-tool analyze" in commands
        assert any("focus" in c and "retrieve" in c for c in commands)


class TestUninstallHooks:
    """Tests for hook removal."""

    def test_removes_focus_hooks_only(self, tmp_path):
        """Uninstall removes only Focus hooks, preserves others."""
        settings_path = tmp_path / "settings.json"
        data = {
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "focus retrieve --hook"}]},
                    {"hooks": [{"type": "command", "command": "other-tool thing"}]},
                ],
                "Stop": [
                    {"hooks": [{"type": "command", "command": "focus record --hook"}]},
                ],
            }
        }
        settings_path.write_text(json.dumps(data))

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            settings = _read_settings()
            hooks = settings.get("hooks", {})

            for event_name in list(hooks.keys()):
                entries = hooks[event_name]
                if _has_focus_hook(entries):
                    hooks[event_name] = _remove_focus_hooks(entries)
                    if not hooks[event_name]:
                        del hooks[event_name]

            settings["hooks"] = hooks
            _write_settings(settings)

        result = json.loads(settings_path.read_text())
        assert "Stop" not in result["hooks"]
        assert "UserPromptSubmit" in result["hooks"]
        assert len(result["hooks"]["UserPromptSubmit"]) == 1
        assert result["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "other-tool thing"
