"""Tests for the project state module (src/context/project_state.py)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.context.project_state import (
    _read_state,
    _write_state,
    clear_active_project,
    get_active_project,
    list_active_projects,
    set_active_project,
)


@pytest.fixture
def state_file(tmp_path):
    """Override STATE_FILE to use a temp directory."""
    sf = tmp_path / "active_project.json"
    with patch("src.context.project_state.STATE_FILE", sf):
        yield sf


class TestReadState:
    """Tests for _read_state."""

    def test_returns_defaults_when_no_file(self, state_file):
        result = _read_state()
        assert result == {"global": None, "workspaces": {}}

    def test_reads_existing_file(self, state_file):
        state_file.write_text(json.dumps({"global": "focus", "workspaces": {"/home/user/focus": "focus"}}))
        result = _read_state()
        assert result["global"] == "focus"
        assert result["workspaces"]["/home/user/focus"] == "focus"

    def test_handles_corrupt_json(self, state_file):
        state_file.write_text("not json{{{")
        result = _read_state()
        assert result == {"global": None, "workspaces": {}}

    def test_handles_non_dict_json(self, state_file):
        state_file.write_text('"just a string"')
        result = _read_state()
        assert result == {"global": None, "workspaces": {}}

    def test_fills_missing_keys(self, state_file):
        state_file.write_text(json.dumps({"global": "test"}))
        result = _read_state()
        assert result["global"] == "test"
        assert result["workspaces"] == {}


class TestWriteState:
    """Tests for _write_state."""

    def test_creates_file(self, state_file):
        _write_state({"global": "focus", "workspaces": {}})
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["global"] == "focus"

    def test_creates_parent_dirs(self, tmp_path):
        sf = tmp_path / "nested" / "deep" / "active_project.json"
        with patch("src.context.project_state.STATE_FILE", sf):
            _write_state({"global": "test", "workspaces": {}})
        assert sf.exists()

    def test_overwrites_existing(self, state_file):
        _write_state({"global": "first", "workspaces": {}})
        _write_state({"global": "second", "workspaces": {}})
        data = json.loads(state_file.read_text())
        assert data["global"] == "second"


class TestGetActiveProject:
    """Tests for get_active_project."""

    def test_returns_none_when_no_state(self, state_file):
        assert get_active_project() is None

    def test_returns_global_project(self, state_file):
        state_file.write_text(json.dumps({"global": "focus", "workspaces": {}}))
        assert get_active_project() == "focus"

    def test_workspace_overrides_global(self, state_file):
        state_file.write_text(json.dumps({
            "global": "global-project",
            "workspaces": {"/home/user/focus": "focus"},
        }))
        assert get_active_project(workspace="/home/user/focus") == "focus"

    def test_falls_back_to_global_for_unknown_workspace(self, state_file):
        state_file.write_text(json.dumps({
            "global": "global-project",
            "workspaces": {"/home/user/focus": "focus"},
        }))
        assert get_active_project(workspace="/home/user/other") == "global-project"

    def test_returns_none_for_no_match(self, state_file):
        state_file.write_text(json.dumps({
            "global": None,
            "workspaces": {},
        }))
        assert get_active_project(workspace="/home/user/other") is None


class TestSetActiveProject:
    """Tests for set_active_project."""

    def test_sets_global(self, state_file):
        set_active_project("focus")
        data = json.loads(state_file.read_text())
        assert data["global"] == "focus"

    def test_sets_workspace(self, state_file):
        set_active_project("focus", workspace="/home/user/focus")
        data = json.loads(state_file.read_text())
        assert data["workspaces"]["/home/user/focus"] == "focus"
        assert data["global"] is None

    def test_preserves_existing_workspaces(self, state_file):
        set_active_project("proj-a", workspace="/home/user/a")
        set_active_project("proj-b", workspace="/home/user/b")
        data = json.loads(state_file.read_text())
        assert data["workspaces"]["/home/user/a"] == "proj-a"
        assert data["workspaces"]["/home/user/b"] == "proj-b"

    def test_overwrites_workspace(self, state_file):
        set_active_project("old", workspace="/home/user/focus")
        set_active_project("new", workspace="/home/user/focus")
        data = json.loads(state_file.read_text())
        assert data["workspaces"]["/home/user/focus"] == "new"


class TestClearActiveProject:
    """Tests for clear_active_project."""

    def test_clears_global(self, state_file):
        set_active_project("focus")
        clear_active_project()
        data = json.loads(state_file.read_text())
        assert data["global"] is None

    def test_clears_workspace(self, state_file):
        set_active_project("focus", workspace="/home/user/focus")
        clear_active_project(workspace="/home/user/focus")
        data = json.loads(state_file.read_text())
        assert "/home/user/focus" not in data["workspaces"]

    def test_clear_nonexistent_workspace_is_noop(self, state_file):
        set_active_project("focus")
        clear_active_project(workspace="/nonexistent")
        data = json.loads(state_file.read_text())
        assert data["global"] == "focus"


class TestListActiveProjects:
    """Tests for list_active_projects."""

    def test_returns_full_state(self, state_file):
        set_active_project("focus")
        set_active_project("other", workspace="/home/user/other")
        result = list_active_projects()
        assert result["global"] == "focus"
        assert result["workspaces"]["/home/user/other"] == "other"

    def test_returns_defaults_when_no_state(self, state_file):
        result = list_active_projects()
        assert result == {"global": None, "workspaces": {}}
