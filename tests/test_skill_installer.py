"""Tests for src/skills/installer.py."""

import pytest

from src.skills.installer import (
    InstalledSkill,
    _parse_frontmatter,
    install_skill,
    list_installed_skills,
    uninstall_skill,
    validate_skill_content,
)


VALID_SKILL = """---
name: test-skill
description: A test skill for testing
---

Follow these steps:
1. Do the first thing
2. Do the second thing
"""

VALID_SKILL_WITH_TOOLS = """---
name: deploy
description: Deploy the application
allowed-tools: Bash, Read
---

Run the deployment script.
"""

NO_FRONTMATTER = """Just some instructions without frontmatter."""

EMPTY_BODY = """---
name: test
description: A test
---
"""

BAD_NAME = """---
name: INVALID NAME!
description: A test
---

Body here.
"""


class TestParseFrontmatter:
    def test_basic_frontmatter(self):
        result = _parse_frontmatter(VALID_SKILL)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test skill for testing"

    def test_no_frontmatter(self):
        result = _parse_frontmatter(NO_FRONTMATTER)
        assert result == {}

    def test_with_tools(self):
        result = _parse_frontmatter(VALID_SKILL_WITH_TOOLS)
        assert result["allowed-tools"] == "Bash, Read"

    def test_empty_string(self):
        result = _parse_frontmatter("")
        assert result == {}


class TestValidateSkillContent:
    def test_valid_content(self):
        errors = validate_skill_content(VALID_SKILL)
        assert errors == []

    def test_empty_content(self):
        errors = validate_skill_content("")
        assert len(errors) > 0
        assert "empty" in errors[0].lower()

    def test_no_frontmatter(self):
        errors = validate_skill_content(NO_FRONTMATTER)
        assert len(errors) > 0
        assert "frontmatter" in errors[0].lower()

    def test_empty_body(self):
        errors = validate_skill_content(EMPTY_BODY)
        assert any("body" in e.lower() for e in errors)

    def test_bad_name(self):
        errors = validate_skill_content(BAD_NAME)
        assert any("name" in e.lower() for e in errors)

    def test_missing_description(self):
        content = "---\nname: test\n---\n\nBody here."
        errors = validate_skill_content(content)
        assert any("description" in e.lower() for e in errors)


class TestInstallSkill:
    def test_install_personal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        path = install_skill("test-skill", VALID_SKILL)
        assert path.exists()
        assert path.name == "SKILL.md"
        assert "test-skill" in str(path.parent)
        assert path.read_text() == VALID_SKILL

    def test_install_project(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        path = install_skill(
            "test-skill", VALID_SKILL, scope="project", project_path=project_dir
        )
        assert path.exists()
        assert ".claude" in str(path)

    def test_install_with_supporting_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        path = install_skill(
            "test-skill",
            VALID_SKILL,
            supporting_files={"template.md": "# Template", "scripts/run.sh": "#!/bin/bash"},
        )
        assert path.exists()
        assert (path.parent / "template.md").exists()
        assert (path.parent / "scripts" / "run.sh").exists()

    def test_install_already_exists_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        install_skill("test-skill", VALID_SKILL)

        with pytest.raises(FileExistsError):
            install_skill("test-skill", VALID_SKILL)

    def test_install_force_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        install_skill("test-skill", VALID_SKILL)
        path = install_skill("test-skill", VALID_SKILL, force=True)
        assert path.exists()

    def test_install_invalid_content_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        with pytest.raises(ValueError):
            install_skill("test-skill", "invalid content")


class TestUninstallSkill:
    def test_uninstall_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        install_skill("test-skill", VALID_SKILL)
        assert uninstall_skill("test-skill") is True
        assert not (tmp_path / "skills" / "test-skill").exists()

    def test_uninstall_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")
        assert uninstall_skill("nonexistent") is False


class TestListInstalledSkills:
    def test_list_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")
        skills = list_installed_skills(scope="personal")
        assert skills == []

    def test_list_personal(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")

        install_skill("skill-a", VALID_SKILL)
        install_skill("deploy", VALID_SKILL_WITH_TOOLS, force=True)

        skills = list_installed_skills(scope="personal")
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert "deploy" in names
        assert "test-skill" in names  # from VALID_SKILL frontmatter

    def test_list_with_scope(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")
        install_skill("test-skill", VALID_SKILL)

        skills = list_installed_skills(scope="personal")
        assert all(s.scope == "personal" for s in skills)

    def test_list_parses_description(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.skills.installer.PERSONAL_SKILLS_DIR", tmp_path / "skills")
        install_skill("test-skill", VALID_SKILL)

        skills = list_installed_skills(scope="personal")
        assert skills[0].description == "A test skill for testing"
