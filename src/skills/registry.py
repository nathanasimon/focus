"""Public skill registry — search and install skills from GitHub."""

import logging
import os
import re
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from src.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_REGISTRIES = [
    "anthropics/skills",
    "travisvn/awesome-claude-skills",
]

GITHUB_API = "https://api.github.com"


class RegistrySkill(BaseModel):
    """A skill from a public registry."""

    name: str
    description: str = ""
    source_repo: str
    source_path: str = ""
    source_url: str = ""
    skill_md_content: str = ""
    supporting_files: dict[str, str] = Field(default_factory=dict)


class AwesomeListEntry(BaseModel):
    """An entry from an awesome-list repo."""

    name: str
    description: str = ""
    url: str = ""
    repo: Optional[str] = None


def _github_headers() -> dict[str, str]:
    """Build GitHub API headers with optional auth token."""
    settings = get_settings()
    token = settings.skills.github_token or os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


async def fetch_awesome_list(repo: str) -> list[AwesomeListEntry]:
    """Parse an awesome-list README.md for skill links.

    Args:
        repo: GitHub repo in "owner/repo" format.

    Returns:
        List of skill entries with names, descriptions, and URLs.
    """
    url = f"{GITHUB_API}/repos/{repo}/readme"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_github_headers())
        if resp.status_code != 200:
            logger.warning("Failed to fetch README from %s: %d", repo, resp.status_code)
            return []

        data = resp.json()
        # README content is base64-encoded
        import base64

        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

    entries = []
    # Parse markdown links: - [Name](url) - Description
    # Also: - **[Name](url)** - Description
    link_pattern = re.compile(
        r"-\s+\*?\*?\[([^\]]+)\]\(([^)]+)\)\*?\*?\s*[-–—:]?\s*(.*)"
    )

    for line in content.split("\n"):
        match = link_pattern.match(line.strip())
        if not match:
            continue

        name = match.group(1).strip()
        link_url = match.group(2).strip()
        desc = match.group(3).strip()

        # Extract repo from GitHub URLs
        gh_match = re.match(r"https?://github\.com/([^/]+/[^/]+)", link_url)
        entry_repo = gh_match.group(1) if gh_match else None

        entries.append(
            AwesomeListEntry(
                name=name,
                description=desc,
                url=link_url,
                repo=entry_repo,
            )
        )

    return entries


async def _search_repo_skills(repo: str) -> list[RegistrySkill]:
    """List skill directories in a GitHub repo's skills/ directory.

    Args:
        repo: GitHub repo in "owner/repo" format.

    Returns:
        List of skills found in the repo.
    """
    # Try common skill directory locations
    for path_prefix in ["skills", ".", ""]:
        url = f"{GITHUB_API}/repos/{repo}/contents/{path_prefix}" if path_prefix else f"{GITHUB_API}/repos/{repo}/contents"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_github_headers())
            if resp.status_code != 200:
                continue

            items = resp.json()
            if not isinstance(items, list):
                continue

            skills = []
            for item in items:
                if item.get("type") != "dir":
                    continue

                dir_name = item["name"]
                skill_url = f"{GITHUB_API}/repos/{repo}/contents/{item['path']}/SKILL.md"

                async with httpx.AsyncClient(timeout=15) as inner_client:
                    skill_resp = await inner_client.get(skill_url, headers=_github_headers())
                    if skill_resp.status_code != 200:
                        continue

                    import base64

                    skill_data = skill_resp.json()
                    content = base64.b64decode(
                        skill_data.get("content", "")
                    ).decode("utf-8", errors="replace")

                    skills.append(
                        RegistrySkill(
                            name=dir_name,
                            description=_extract_description(content),
                            source_repo=repo,
                            source_path=item["path"],
                            source_url=item.get("html_url", ""),
                            skill_md_content=content,
                        )
                    )

            if skills:
                return skills

    return []


def _extract_description(content: str) -> str:
    """Extract description from SKILL.md frontmatter."""
    if not content.startswith("---"):
        return ""

    for line in content.split("\n")[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()

    return ""


async def search_skills(
    query: str,
    sources: Optional[list[str]] = None,
) -> list[RegistrySkill]:
    """Search public skill registries for matching skills.

    Args:
        query: Search query.
        sources: Optional list of specific repos to search.

    Returns:
        List of matching skills with metadata.
    """
    repos = sources or DEFAULT_REGISTRIES
    results: list[RegistrySkill] = []
    query_lower = query.lower()

    for repo in repos:
        try:
            # First try: direct skill repo (has SKILL.md files)
            skills = await _search_repo_skills(repo)
            for skill in skills:
                if (
                    query_lower in skill.name.lower()
                    or query_lower in skill.description.lower()
                ):
                    results.append(skill)

            # Second try: awesome-list repo (has markdown links)
            if not skills:
                entries = await fetch_awesome_list(repo)
                for entry in entries:
                    if (
                        query_lower in entry.name.lower()
                        or query_lower in entry.description.lower()
                    ):
                        results.append(
                            RegistrySkill(
                                name=entry.name,
                                description=entry.description,
                                source_repo=repo,
                                source_url=entry.url,
                            )
                        )

        except httpx.HTTPError as e:
            logger.warning("Error searching %s: %s", repo, e)
        except Exception as e:
            logger.warning("Unexpected error searching %s: %s", repo, e)

    return results


async def fetch_skill_from_github(
    repo: str,
    skill_path: str,
) -> Optional[RegistrySkill]:
    """Fetch a SKILL.md and supporting files from a GitHub repo.

    Args:
        repo: GitHub repo in "owner/repo" format.
        skill_path: Path to skill directory within the repo.

    Returns:
        RegistrySkill with content, or None if not found.
    """
    url = f"{GITHUB_API}/repos/{repo}/contents/{skill_path}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_github_headers())
        if resp.status_code != 200:
            logger.warning("Failed to fetch %s/%s: %d", repo, skill_path, resp.status_code)
            return None

        items = resp.json()
        if not isinstance(items, list):
            items = [items]

        import base64

        skill_content = ""
        supporting_files: dict[str, str] = {}
        name = skill_path.rstrip("/").split("/")[-1]

        for item in items:
            if item.get("type") != "file":
                continue

            file_name = item["name"]
            file_url = item.get("download_url", "")

            if file_name == "SKILL.md":
                file_resp = await client.get(file_url, timeout=15)
                if file_resp.status_code == 200:
                    skill_content = file_resp.text
            else:
                file_resp = await client.get(file_url, timeout=15)
                if file_resp.status_code == 200:
                    supporting_files[file_name] = file_resp.text

        if not skill_content:
            logger.warning("No SKILL.md found in %s/%s", repo, skill_path)
            return None

        return RegistrySkill(
            name=name,
            description=_extract_description(skill_content),
            source_repo=repo,
            source_path=skill_path,
            source_url=f"https://github.com/{repo}/tree/main/{skill_path}",
            skill_md_content=skill_content,
            supporting_files=supporting_files,
        )
