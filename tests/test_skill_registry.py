"""Tests for src/skills/registry.py."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.skills.registry import (
    AwesomeListEntry,
    RegistrySkill,
    _extract_description,
    fetch_awesome_list,
    fetch_skill_from_github,
    search_skills,
)


SAMPLE_SKILL_MD = """---
name: deploy-app
description: Deploy application to production
---

1. Build the project
2. Push to server
"""

SAMPLE_README = """# Awesome Claude Skills

## Skills

- [Deploy Helper](https://github.com/user/deploy-skill) - Deploy apps easily
- [Test Runner](https://github.com/user/test-runner) - Run tests with coverage
- **[Code Review](https://github.com/user/code-review)** — Automated code reviews
- [Unrelated Link](https://example.com) - Not a GitHub repo
"""


class TestExtractDescription:
    def test_basic(self):
        result = _extract_description(SAMPLE_SKILL_MD)
        assert result == "Deploy application to production"

    def test_no_frontmatter(self):
        result = _extract_description("Just some text")
        assert result == ""

    def test_no_description(self):
        result = _extract_description("---\nname: test\n---\nBody")
        assert result == ""


class TestFetchAwesomeList:
    @pytest.mark.asyncio
    async def test_parses_readme(self):
        readme_b64 = base64.b64encode(SAMPLE_README.encode()).decode()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": readme_b64}

        with patch("src.skills.registry.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            entries = await fetch_awesome_list("user/awesome-list")

        assert len(entries) >= 3
        names = {e.name for e in entries}
        assert "Deploy Helper" in names
        assert "Test Runner" in names

    @pytest.mark.asyncio
    async def test_handles_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("src.skills.registry.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            entries = await fetch_awesome_list("user/nonexistent")

        assert entries == []

    @pytest.mark.asyncio
    async def test_extracts_repo(self):
        readme_b64 = base64.b64encode(SAMPLE_README.encode()).decode()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": readme_b64}

        with patch("src.skills.registry.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            entries = await fetch_awesome_list("user/awesome-list")

        github_entries = [e for e in entries if e.repo]
        assert len(github_entries) >= 2


class TestSearchSkills:
    @pytest.mark.asyncio
    async def test_search_filters_by_query(self):
        # Mock _search_repo_skills to return nothing
        # Mock fetch_awesome_list to return entries
        entries = [
            AwesomeListEntry(name="Deploy App", description="Deploy helper", url="https://github.com/user/deploy"),
            AwesomeListEntry(name="Test Runner", description="Run tests", url="https://github.com/user/test"),
        ]

        with patch("src.skills.registry._search_repo_skills", return_value=[]), \
             patch("src.skills.registry.fetch_awesome_list", return_value=entries):

            results = await search_skills("deploy", sources=["user/awesome-list"])

        assert len(results) == 1
        assert results[0].name == "Deploy App"

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        with patch("src.skills.registry._search_repo_skills", return_value=[]), \
             patch("src.skills.registry.fetch_awesome_list", return_value=[]):

            results = await search_skills("nonexistent", sources=["user/repo"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_errors(self):
        with patch("src.skills.registry._search_repo_skills", side_effect=httpx.HTTPError("timeout")), \
             patch("src.skills.registry.fetch_awesome_list", side_effect=httpx.HTTPError("timeout")):

            results = await search_skills("deploy", sources=["user/repo"])

        assert results == []


class TestFetchSkillFromGithub:
    @pytest.mark.asyncio
    async def test_fetches_skill(self):
        # Mock directory listing
        dir_resp = MagicMock()
        dir_resp.status_code = 200
        dir_resp.json.return_value = [
            {"name": "SKILL.md", "type": "file", "download_url": "https://raw.githubusercontent.com/user/repo/main/skills/deploy/SKILL.md"},
            {"name": "template.md", "type": "file", "download_url": "https://raw.githubusercontent.com/user/repo/main/skills/deploy/template.md"},
        ]

        # Mock file download
        skill_resp = MagicMock()
        skill_resp.status_code = 200
        skill_resp.text = SAMPLE_SKILL_MD

        template_resp = MagicMock()
        template_resp.status_code = 200
        template_resp.text = "# Template"

        with patch("src.skills.registry.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [dir_resp, skill_resp, template_resp]
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await fetch_skill_from_github("user/repo", "skills/deploy")

        assert result is not None
        assert result.name == "deploy"
        assert "Deploy application" in result.skill_md_content
        assert "template.md" in result.supporting_files

    @pytest.mark.asyncio
    async def test_404_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("src.skills.registry.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await fetch_skill_from_github("user/repo", "skills/nonexistent")

        assert result is None
