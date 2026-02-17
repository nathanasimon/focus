"""Tests for src/skills/generator.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.skills.generator import (
    GeneratedSkill,
    SkillContext,
    _build_generation_prompt,
    _parse_generation_response,
    generate_skill_md,
    render_skill_md,
    validate_skill_name,
)


class TestValidateSkillName:
    def test_valid_name(self):
        assert validate_skill_name("deploy-app") == "deploy-app"

    def test_uppercase_lowered(self):
        assert validate_skill_name("Deploy-App") == "deploy-app"

    def test_spaces_to_hyphens(self):
        assert validate_skill_name("deploy my app") == "deploy-my-app"

    def test_special_chars_to_hyphens(self):
        assert validate_skill_name("deploy_my_app!") == "deploy-my-app"

    def test_consecutive_hyphens_collapsed(self):
        assert validate_skill_name("deploy--my---app") == "deploy-my-app"

    def test_leading_trailing_hyphens_stripped(self):
        assert validate_skill_name("-deploy-app-") == "deploy-app"

    def test_too_long_truncated(self):
        long_name = "a" * 100
        result = validate_skill_name(long_name)
        assert len(result) <= 64

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_skill_name("!!!")

    def test_single_char(self):
        assert validate_skill_name("a") == "a"


class TestRenderSkillMd:
    def test_basic(self):
        result = render_skill_md(
            name="test-skill",
            description="A test skill",
            body="Do the thing.",
        )
        assert "---" in result
        assert "name: test-skill" in result
        assert "description: A test skill" in result
        assert "Do the thing." in result

    def test_with_allowed_tools(self):
        result = render_skill_md(
            name="test-skill",
            description="A test",
            body="Instructions",
            allowed_tools=["Read", "Write", "Bash"],
        )
        assert "allowed-tools: Read, Write, Bash" in result

    def test_with_disable_model_invocation(self):
        result = render_skill_md(
            name="test-skill",
            description="A test",
            body="Instructions",
            disable_model_invocation=True,
        )
        assert "disable-model-invocation: true" in result

    def test_body_stripped(self):
        result = render_skill_md(
            name="test",
            description="A test",
            body="\n  Instructions\n\n  ",
        )
        assert "Instructions" in result

    def test_valid_yaml_frontmatter(self):
        result = render_skill_md(
            name="test",
            description="A test",
            body="Body",
        )
        lines = result.split("\n")
        assert lines[0] == "---"
        # Find closing ---
        close_idx = None
        for i, line in enumerate(lines[1:], 1):
            if line == "---":
                close_idx = i
                break
        assert close_idx is not None


class TestBuildGenerationPrompt:
    def test_basic_description(self):
        ctx = SkillContext()
        result = _build_generation_prompt("Deploy my app", ctx)
        assert "Deploy my app" in result

    def test_with_workspace(self):
        ctx = SkillContext(workspace_path="/home/user/project")
        result = _build_generation_prompt("Deploy", ctx)
        assert "/home/user/project" in result

    def test_with_files(self):
        ctx = SkillContext(files_touched=["src/main.py", "tests/test_main.py"])
        result = _build_generation_prompt("Test", ctx)
        assert "src/main.py" in result

    def test_with_session_summary(self):
        ctx = SkillContext(session_summary="Did some important work")
        result = _build_generation_prompt("Work", ctx)
        assert "Did some important work" in result

    def test_truncates_long_summary(self):
        ctx = SkillContext(session_summary="x" * 5000)
        result = _build_generation_prompt("Work", ctx)
        assert len(result) < 5000 + 500  # Some overhead


class TestParseGenerationResponse:
    def test_plain_json(self):
        raw = json.dumps({
            "name": "test-skill",
            "description": "A test",
            "body": "Instructions",
            "allowed_tools": ["Read"],
        })
        result = _parse_generation_response(raw)
        assert result["name"] == "test-skill"
        assert result["body"] == "Instructions"

    def test_json_in_code_fence(self):
        raw = '```json\n{"name": "test", "description": "A test", "body": "Do it"}\n```'
        result = _parse_generation_response(raw)
        assert result["name"] == "test"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_generation_response("not json")


class TestGenerateSkillMd:
    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock()
        settings.anthropic.api_key = "test-key"
        settings.skills.skill_generation_model = "claude-haiku-4-5-20251001"
        settings.raw_storage.store_ai_conversations = False
        return settings

    @pytest.fixture
    def mock_response(self):
        resp = MagicMock()
        resp.content = [MagicMock()]
        resp.content[0].text = json.dumps({
            "name": "deploy-app",
            "description": "Deploy the application",
            "body": "1. Build the app\n2. Push to server",
            "allowed_tools": ["Bash"],
        })
        resp.usage.input_tokens = 100
        resp.usage.output_tokens = 50
        return resp

    @pytest.mark.asyncio
    async def test_generates_skill(self, mock_settings, mock_response):
        with patch("src.skills.generator.get_settings", return_value=mock_settings), \
             patch("src.skills.generator.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response

            result = await generate_skill_md(
                "Deploy my app",
                SkillContext(),
            )

            assert result is not None
            assert result.name == "deploy-app"
            assert "Deploy the application" in result.description
            assert result.full_content.startswith("---")

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        settings = MagicMock()
        settings.anthropic.api_key = ""
        with patch("src.skills.generator.get_settings", return_value=settings):
            result = await generate_skill_md("Test", SkillContext())
            assert result is None

    @pytest.mark.asyncio
    async def test_malformed_response_returns_none(self, mock_settings):
        bad_resp = MagicMock()
        bad_resp.content = [MagicMock()]
        bad_resp.content[0].text = "not valid json"
        bad_resp.usage.input_tokens = 10
        bad_resp.usage.output_tokens = 5

        with patch("src.skills.generator.get_settings", return_value=mock_settings), \
             patch("src.skills.generator.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = bad_resp

            result = await generate_skill_md("Test", SkillContext())
            assert result is None

    @pytest.mark.asyncio
    async def test_empty_body_returns_none(self, mock_settings):
        resp = MagicMock()
        resp.content = [MagicMock()]
        resp.content[0].text = json.dumps({
            "name": "test",
            "description": "test",
            "body": "",
        })
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5

        with patch("src.skills.generator.get_settings", return_value=mock_settings), \
             patch("src.skills.generator.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = resp

            result = await generate_skill_md("Test", SkillContext())
            assert result is None

    @pytest.mark.asyncio
    async def test_source_preserved(self, mock_settings, mock_response):
        with patch("src.skills.generator.get_settings", return_value=mock_settings), \
             patch("src.skills.generator.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_response

            result = await generate_skill_md("Test", SkillContext(), source="auto")
            assert result.source == "auto"
