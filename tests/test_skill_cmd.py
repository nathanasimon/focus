"""Tests for src/cli/skill_cmd.py."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.skill_cmd import app
from src.skills.generator import GeneratedSkill
from src.skills.installer import InstalledSkill
from src.skills.registry import RegistrySkill

runner = CliRunner()


VALID_SKILL_CONTENT = """---
name: test-skill
description: A test skill
---

Do the thing.
"""


class TestCreateCommand:
    def test_create_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        mock_skill = GeneratedSkill(
            name="test-skill",
            description="A test skill",
            body="Do the thing.",
            full_content=VALID_SKILL_CONTENT,
            source="manual",
        )

        with patch("src.skills.generator.generate_skill_md", return_value=mock_skill):
            result = runner.invoke(app, ["create", "Do a test thing"])

        assert result.exit_code == 0
        assert "test-skill" in result.output

    def test_create_fails_no_api_key(self):
        with patch("src.skills.generator.generate_skill_md", return_value=None):
            result = runner.invoke(app, ["create", "Do something"])

        assert result.exit_code == 1
        assert "Failed" in result.output


class TestListCommand:
    def test_list_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        result = runner.invoke(app, ["list", "--scope", "personal"])
        assert result.exit_code == 0
        assert "No skills" in result.output

    def test_list_with_skills(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        # Install a skill first
        from src.skills.installer import install_skill

        install_skill("test-skill", VALID_SKILL_CONTENT)

        result = runner.invoke(app, ["list", "--scope", "personal"])
        assert result.exit_code == 0
        assert "test-skill" in result.output


class TestShowCommand:
    def test_show_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        from src.skills.installer import install_skill

        install_skill("test-skill", VALID_SKILL_CONTENT)

        result = runner.invoke(app, ["show", "test-skill", "--scope", "personal"])
        assert result.exit_code == 0
        assert "Do the thing" in result.output

    def test_show_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        result = runner.invoke(app, ["show", "nonexistent", "--scope", "personal"])
        assert result.exit_code == 1


class TestUninstallCommand:
    def test_uninstall_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        from src.skills.installer import install_skill

        install_skill("test-skill", VALID_SKILL_CONTENT)

        result = runner.invoke(app, ["uninstall", "test-skill"])
        assert result.exit_code == 0
        assert "Uninstalled" in result.output

    def test_uninstall_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        result = runner.invoke(app, ["uninstall", "nonexistent"])
        assert result.exit_code == 1


class TestSearchCommand:
    def test_search_with_results(self):
        mock_results = [
            RegistrySkill(
                name="deploy-tool",
                description="Deploy apps",
                source_repo="user/skills",
                source_url="https://github.com/user/skills/deploy",
            ),
        ]

        with patch("src.skills.registry.search_skills", return_value=mock_results):
            result = runner.invoke(app, ["search", "deploy"])

        assert result.exit_code == 0
        assert "deploy-tool" in result.output

    def test_search_no_results(self):
        with patch("src.skills.registry.search_skills", return_value=[]):
            result = runner.invoke(app, ["search", "nonexistent"])

        assert result.exit_code == 0
        assert "No skills found" in result.output
