"""Skill installation — write SKILL.md files to disk and manage them."""

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PERSONAL_SKILLS_DIR = Path.home() / ".claude" / "skills"
PROJECT_SKILLS_DIR = Path(".claude") / "skills"


class InstalledSkill(BaseModel):
    """An installed skill on disk."""

    name: str
    description: str = ""
    path: Path
    scope: str  # "personal" or "project"
    source: Optional[str] = None


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from SKILL.md content.

    Args:
        content: Full SKILL.md content string.

    Returns:
        Dict of frontmatter fields.
    """
    if not content.startswith("---"):
        return {}

    lines = content.split("\n")
    end_idx = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}

    frontmatter = {}
    for line in lines[1:end_idx]:
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()

    return frontmatter


def validate_skill_content(content: str) -> list[str]:
    """Validate SKILL.md content against the Agent Skills spec.

    Args:
        content: Full SKILL.md content string.

    Returns:
        List of validation errors (empty if valid).
    """
    errors = []

    if not content.strip():
        errors.append("Skill content is empty")
        return errors

    if not content.startswith("---"):
        errors.append("Missing YAML frontmatter (must start with ---)")
        return errors

    fm = _parse_frontmatter(content)

    if "name" in fm:
        name = fm["name"]
        if not re.match(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$", name):
            errors.append(
                f"Invalid skill name '{name}': must be lowercase alphanumeric + hyphens"
            )
        if len(name) > 64:
            errors.append(f"Skill name too long ({len(name)} > 64 chars)")

    if "description" not in fm or not fm["description"]:
        errors.append("Missing or empty 'description' field in frontmatter")

    # Check body exists after frontmatter
    parts = content.split("---", 2)
    if len(parts) < 3 or not parts[2].strip():
        errors.append("Missing instruction body after frontmatter")

    return errors


def _get_skills_dir(
    scope: str,
    project_path: Optional[Path] = None,
) -> Path:
    """Get the skills directory for the given scope."""
    if scope == "project":
        base = Path(project_path) if project_path else Path.cwd()
        return base / ".claude" / "skills"
    return PERSONAL_SKILLS_DIR


def install_skill(
    name: str,
    content: str,
    scope: str = "personal",
    project_path: Optional[Path] = None,
    force: bool = False,
    supporting_files: Optional[dict[str, str]] = None,
) -> Path:
    """Install a skill to the filesystem.

    Args:
        name: Skill name (used as directory name).
        content: Complete SKILL.md content.
        scope: "personal" or "project".
        project_path: Required if scope is "project".
        force: Overwrite existing skill with same name.
        supporting_files: Optional dict of filename -> content.

    Returns:
        Path to the installed SKILL.md.

    Raises:
        FileExistsError: If skill exists and force is False.
        ValueError: If content fails validation.
    """
    errors = validate_skill_content(content)
    if errors:
        raise ValueError(f"Invalid skill content: {'; '.join(errors)}")

    skills_dir = _get_skills_dir(scope, project_path)
    skill_dir = skills_dir / name

    if skill_dir.exists() and not force:
        raise FileExistsError(
            f"Skill '{name}' already exists at {skill_dir}. Use --force to overwrite."
        )

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(content)

    if supporting_files:
        for filename, file_content in supporting_files.items():
            file_path = skill_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(file_content)

    logger.info("Installed skill '%s' at %s", name, skill_path)
    return skill_path


def uninstall_skill(
    name: str,
    scope: str = "personal",
    project_path: Optional[Path] = None,
) -> bool:
    """Remove an installed skill.

    Args:
        name: Skill name to remove.
        scope: "personal" or "project".
        project_path: Required if scope is "project".

    Returns:
        True if skill was removed, False if not found.
    """
    skills_dir = _get_skills_dir(scope, project_path)
    skill_dir = skills_dir / name

    if not skill_dir.exists():
        return False

    shutil.rmtree(skill_dir)
    logger.info("Uninstalled skill '%s' from %s", name, skill_dir)
    return True


def list_installed_skills(
    scope: str = "all",
    project_path: Optional[Path] = None,
) -> list[InstalledSkill]:
    """List all installed skills.

    Args:
        scope: "personal", "project", or "all".
        project_path: Required if scope includes "project".

    Returns:
        List of installed skills with metadata from frontmatter.
    """
    skills = []

    dirs_to_scan = []
    if scope in ("personal", "all"):
        dirs_to_scan.append(("personal", PERSONAL_SKILLS_DIR))
    if scope in ("project", "all"):
        proj_dir = _get_skills_dir("project", project_path)
        dirs_to_scan.append(("project", proj_dir))

    for skill_scope, skills_dir in dirs_to_scan:
        if not skills_dir.exists():
            continue

        for entry in sorted(skills_dir.iterdir()):
            skill_md = entry / "SKILL.md"
            if not entry.is_dir() or not skill_md.exists():
                continue

            content = skill_md.read_text()
            fm = _parse_frontmatter(content)

            skills.append(
                InstalledSkill(
                    name=fm.get("name", entry.name),
                    description=fm.get("description", ""),
                    path=skill_md,
                    scope=skill_scope,
                    source=fm.get("source"),
                )
            )

    return skills
