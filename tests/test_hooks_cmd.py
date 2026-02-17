"""Tests for the hooks CLI commands (src/cli/hooks_cmd.py)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli.hooks_cmd import (
    _build_hook_command,
    _get_focus_bin,
    _has_focus_hook,
    _is_focus_command,
    _remove_focus_hooks,
    get_focus_hooks,
)


class TestGetFocusBin:
    """Tests for _get_focus_bin."""

    def test_finds_via_shutil_which(self):
        with patch("shutil.which", return_value="/usr/local/bin/focus"):
            assert _get_focus_bin() == "/usr/local/bin/focus"

    def test_falls_back_to_venv_bin(self, tmp_path):
        venv_bin = tmp_path / "focus"
        venv_bin.touch()
        fake_python = tmp_path / "python"
        with patch("shutil.which", return_value=None):
            with patch.object(sys, "executable", str(fake_python)):
                assert _get_focus_bin() == str(venv_bin)

    def test_falls_back_to_bare_focus(self, tmp_path):
        fake_python = tmp_path / "nonexistent" / "python"
        with patch("shutil.which", return_value=None):
            with patch.object(sys, "executable", str(fake_python)):
                assert _get_focus_bin() == "focus"


class TestBuildHookCommand:
    """Tests for _build_hook_command."""

    def test_wraps_in_bash(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
            cmd = _build_hook_command("record --hook")
        assert cmd.startswith("bash -c '")
        assert "/path/to/focus record --hook" in cmd
        assert "2>/dev/null || true" in cmd

    def test_uses_actual_binary_path(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/custom/focus"):
            cmd = _build_hook_command("retrieve --hook")
        assert "/custom/focus retrieve --hook" in cmd


class TestIsFocusCommand:
    """Tests for _is_focus_command."""

    def test_detects_old_style_bare_command(self):
        assert _is_focus_command("focus record --hook") is True

    def test_detects_new_style_bash_wrapped(self):
        cmd = "bash -c '/home/user/.venv/bin/focus record --hook 2>/dev/null || true'"
        assert _is_focus_command(cmd) is True

    def test_detects_retrieve_command(self):
        cmd = "bash -c '/path/to/focus retrieve --hook 2>/dev/null || true'"
        assert _is_focus_command(cmd) is True

    def test_rejects_unrelated_command(self):
        assert _is_focus_command("echo hello") is False

    def test_rejects_partial_name_match(self):
        assert _is_focus_command("unfocused-tool run") is False

    def test_detects_focus_marker_in_command(self):
        assert _is_focus_command("focus retrieve --hook") is True

    def test_empty_command(self):
        assert _is_focus_command("") is False


class TestHasFocusHook:
    """Tests for _has_focus_hook."""

    def test_finds_focus_in_entries(self):
        entries = [
            {"hooks": [{"type": "command", "command": "focus record --hook"}]}
        ]
        assert _has_focus_hook(entries) is True

    def test_no_focus_hooks(self):
        entries = [
            {"hooks": [{"type": "command", "command": "other-tool run"}]}
        ]
        assert _has_focus_hook(entries) is False

    def test_empty_entries(self):
        assert _has_focus_hook([]) is False

    def test_finds_among_multiple_hooks(self):
        entries = [
            {"hooks": [
                {"type": "command", "command": "other-tool run"},
                {"type": "command", "command": "bash -c '/path/focus record --hook 2>/dev/null || true'"},
            ]}
        ]
        assert _has_focus_hook(entries) is True


class TestRemoveFocusHooks:
    """Tests for _remove_focus_hooks."""

    def test_removes_focus_preserves_others(self):
        entries = [
            {"hooks": [
                {"type": "command", "command": "other-tool run"},
                {"type": "command", "command": "focus record --hook"},
            ]}
        ]
        result = _remove_focus_hooks(entries)
        assert len(result) == 1
        assert len(result[0]["hooks"]) == 1
        assert result[0]["hooks"][0]["command"] == "other-tool run"

    def test_removes_entry_when_only_focus(self):
        entries = [
            {"hooks": [{"type": "command", "command": "focus record --hook"}]}
        ]
        result = _remove_focus_hooks(entries)
        assert result == []

    def test_empty_list(self):
        assert _remove_focus_hooks([]) == []


class TestGetFocusHooks:
    """Tests for get_focus_hooks."""

    def test_returns_both_events(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
            hooks = get_focus_hooks()
        assert "UserPromptSubmit" in hooks
        assert "Stop" in hooks

    def test_retrieve_in_submit_hook(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
            hooks = get_focus_hooks()
        cmd = hooks["UserPromptSubmit"]["hooks"][0]["command"]
        assert "retrieve" in cmd

    def test_record_in_stop_hook(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
            hooks = get_focus_hooks()
        cmd = hooks["Stop"]["hooks"][0]["command"]
        assert "record" in cmd

    def test_hooks_have_timeout(self):
        with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
            hooks = get_focus_hooks()
        assert hooks["UserPromptSubmit"]["hooks"][0]["timeout"] == 5
        assert hooks["Stop"]["hooks"][0]["timeout"] == 10


class TestInstallUninstallIntegration:
    """Integration tests for install/uninstall using temp settings file."""

    def test_install_creates_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
                from src.cli.hooks_cmd import install_hooks
                # Run with default args (force=False)
                from typer.testing import CliRunner
                from typer import Typer

                test_app = Typer()
                test_app.command()(install_hooks)
                runner = CliRunner()
                result = runner.invoke(test_app, [])

        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]
        assert "UserPromptSubmit" in settings["hooks"]

    def test_install_preserves_existing_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "other-tool stop"}]}
                ]
            },
            "other_setting": True,
        }
        settings_path.write_text(json.dumps(existing))

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
                from src.cli.hooks_cmd import install_hooks
                from typer.testing import CliRunner
                from typer import Typer

                test_app = Typer()
                test_app.command()(install_hooks)
                runner = CliRunner()
                result = runner.invoke(test_app, [])

        settings = json.loads(settings_path.read_text())
        assert settings["other_setting"] is True
        # Should have 2 entries in Stop: the existing one + focus
        stop_entries = settings["hooks"]["Stop"]
        assert len(stop_entries) == 2
        # First entry is the existing other-tool
        assert stop_entries[0]["hooks"][0]["command"] == "other-tool stop"

    def test_install_skip_existing_focus_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "focus record --hook"}]}
                ]
            }
        }
        settings_path.write_text(json.dumps(existing))

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            with patch("src.cli.hooks_cmd._get_focus_bin", return_value="/path/to/focus"):
                from src.cli.hooks_cmd import install_hooks
                from typer.testing import CliRunner
                from typer import Typer

                test_app = Typer()
                test_app.command()(install_hooks)
                runner = CliRunner()
                result = runner.invoke(test_app, [])
                assert "Skipping" in result.output or "already installed" in result.output

    def test_uninstall_removes_focus_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "other-tool stop"}]},
                    {"hooks": [{"type": "command", "command": "focus record --hook"}]},
                ],
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "focus retrieve --hook"}]},
                ],
            }
        }
        settings_path.write_text(json.dumps(existing))

        with patch("src.cli.hooks_cmd.CLAUDE_SETTINGS_PATH", settings_path):
            from src.cli.hooks_cmd import uninstall_hooks
            from typer.testing import CliRunner
            from typer import Typer

            test_app = Typer()
            test_app.command()(uninstall_hooks)
            runner = CliRunner()
            result = runner.invoke(test_app, [])

        settings = json.loads(settings_path.read_text())
        # Stop should still have the other-tool entry
        assert len(settings["hooks"]["Stop"]) == 1
        assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "other-tool stop"
        # UserPromptSubmit should be removed entirely
        assert "UserPromptSubmit" not in settings["hooks"]
