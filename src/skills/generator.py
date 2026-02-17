"""Core SKILL.md generation engine.

Generates Claude Code skills from descriptions and project context
using Haiku for instruction generation.
"""

import json
import logging
import re
import time
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from src.config import get_settings

logger = logging.getLogger(__name__)

SKILL_GENERATION_PROMPT_VERSION = "v1.0"

SKILL_GENERATION_SYSTEM = """You generate Claude Code skills (SKILL.md files) following the Agent Skills standard.

Given a description of what the skill should do and context about the project/task,
generate a skill with:

1. A short name (lowercase-with-hyphens, max 64 chars)
2. A description (1-2 sentences explaining what it does and when to use it)
3. Step-by-step markdown instructions for Claude to follow

Your output MUST be valid JSON with these fields:
- name: string (lowercase, hyphens only, max 64 chars)
- description: string (1-2 sentences, max 200 chars)
- body: string (markdown instructions, specific and actionable)
- allowed_tools: list of strings (Claude Code tools this skill needs, e.g. ["Read", "Write", "Bash", "Grep", "Glob"])

Keep instructions concise and specific. Reference file paths, commands, and patterns
from the context when available. Focus on the repeatable workflow, not one-time setup."""


class SkillContext(BaseModel):
    """Context for skill generation."""

    workspace_path: str = ""
    project_slug: Optional[str] = None
    files_touched: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    conventions: str = ""
    session_summary: str = ""


class GeneratedSkill(BaseModel):
    """A generated skill ready for installation."""

    name: str
    description: str
    body: str
    full_content: str = ""
    source: str = "manual"  # "auto", "manual", "registry"
    confidence: float = 1.0
    supporting_files: dict[str, str] = Field(default_factory=dict)


def validate_skill_name(name: str) -> str:
    """Validate and normalize a skill name per Agent Skills spec.

    Args:
        name: Proposed skill name.

    Returns:
        Normalized valid skill name.

    Raises:
        ValueError: If name cannot be made valid.
    """
    normalized = name.lower().strip()
    normalized = re.sub(r"[^a-z0-9\-]", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = normalized.strip("-")

    if not normalized:
        raise ValueError(f"Cannot normalize skill name: {name!r}")

    if len(normalized) > 64:
        normalized = normalized[:64].rstrip("-")

    return normalized


def render_skill_md(
    name: str,
    description: str,
    body: str,
    allowed_tools: Optional[list[str]] = None,
    disable_model_invocation: bool = False,
) -> str:
    """Render a complete SKILL.md file with YAML frontmatter.

    Args:
        name: Skill name (must be valid).
        description: Skill description.
        body: Markdown instructions body.
        allowed_tools: Optional list of pre-approved tools.
        disable_model_invocation: If True, skill is manual-only.

    Returns:
        Complete SKILL.md content string.
    """
    lines = ["---"]
    lines.append(f"name: {name}")
    lines.append(f"description: {description}")

    if allowed_tools:
        tools_str = ", ".join(allowed_tools)
        lines.append(f"allowed-tools: {tools_str}")

    if disable_model_invocation:
        lines.append("disable-model-invocation: true")

    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    lines.append("")

    return "\n".join(lines)


def _build_generation_prompt(description: str, context: SkillContext) -> str:
    """Build the user prompt for skill generation."""
    parts = [f"Generate a Claude Code skill for:\n{description}"]

    if context.workspace_path:
        parts.append(f"\nWorkspace: {context.workspace_path}")

    if context.session_summary:
        parts.append(f"\nSession summary:\n{context.session_summary[:2000]}")

    if context.files_touched:
        files = ", ".join(context.files_touched[:20])
        parts.append(f"\nFiles involved: {files}")

    if context.commands_run:
        cmds = ", ".join(context.commands_run[:10])
        parts.append(f"\nCommands used: {cmds}")

    if context.tools_used:
        tools = ", ".join(context.tools_used[:10])
        parts.append(f"\nTools used: {tools}")

    if context.conventions:
        parts.append(f"\nProject conventions:\n{context.conventions[:1000]}")

    parts.append("\nReturn JSON with: name, description, body, allowed_tools")
    return "\n".join(parts)


def _parse_generation_response(raw_text: str) -> dict:
    """Parse the LLM response into skill fields."""
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # Remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return json.loads(text)


async def generate_skill_md(
    description: str,
    context: SkillContext,
    source: str = "manual",
) -> Optional[GeneratedSkill]:
    """Generate a SKILL.md from a description and project context.

    Uses Haiku to create structured skill instructions.

    Args:
        description: What the skill does.
        context: Project-specific context.
        source: Origin of the skill ("auto", "manual").

    Returns:
        GeneratedSkill if successful, None on failure.
    """
    settings = get_settings()

    if not settings.anthropic.api_key:
        logger.warning("No Anthropic API key configured, cannot generate skill")
        return None

    user_prompt = _build_generation_prompt(description, context)
    messages = [{"role": "user", "content": user_prompt}]
    model = settings.skills.skill_generation_model

    start_time = time.time()

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic.api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=SKILL_GENERATION_SYSTEM,
            messages=messages,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_text = response.content[0].text

        parsed = _parse_generation_response(raw_text)
        name = validate_skill_name(parsed.get("name", ""))
        desc = parsed.get("description", description)[:200]
        body = parsed.get("body", "")
        allowed_tools = parsed.get("allowed_tools", [])

        if not body:
            logger.warning("LLM returned empty skill body")
            return None

        full_content = render_skill_md(
            name=name,
            description=desc,
            body=body,
            allowed_tools=allowed_tools if allowed_tools else None,
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

        logger.info(
            "Generated skill '%s' (cost: $%.4f, latency: %dms)",
            name,
            cost_usd,
            latency_ms,
        )

        return GeneratedSkill(
            name=name,
            description=desc,
            body=body,
            full_content=full_content,
            source=source,
        )

    except json.JSONDecodeError as e:
        logger.error("Failed to parse skill generation response: %s", e)
        return None
    except anthropic.APIError as e:
        logger.error("Anthropic API error during skill generation: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error generating skill: %s", e)
        return None
