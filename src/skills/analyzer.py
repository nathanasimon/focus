"""Session quality analysis for auto-generating skills.

Analyzes completed Claude Code sessions to decide whether they
represent a repeatable pattern worth turning into a skill.
"""

import hashlib
import logging
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.skills.generator import SkillContext
from src.storage.models import (
    AgentSession,
    AgentTurn,
    AgentTurnArtifact,
    AgentTurnContent,
)

logger = logging.getLogger(__name__)


class SkillCandidate(BaseModel):
    """A session that may become a skill."""

    session_id: str
    quality_score: float
    description: str
    context: SkillContext
    workspace_path: str = ""


def score_session_quality(
    turn_count: int,
    error_count: int,
    files_touched: list[str],
    tools_used: list[str],
    has_summary: bool,
) -> float:
    """Score session quality from 0.0 to 1.0.

    Higher scores mean more likely to be a good skill candidate.

    Args:
        turn_count: Number of conversation turns.
        error_count: Number of errors encountered.
        files_touched: Files read/written/edited.
        tools_used: Tool names used across turns.
        has_summary: Whether session has a generated summary.

    Returns:
        Quality score between 0.0 and 1.0.
    """
    score = 0.0

    # Minimum turns (0-0.25)
    if turn_count >= 3:
        score += min(turn_count / 12.0, 0.25)

    # Low error rate (0-0.25)
    if turn_count > 0:
        error_rate = error_count / turn_count
        if error_rate < 0.3:
            score += 0.25 * (1.0 - error_rate)

    # Files touched (0-0.2)
    file_count = len(set(files_touched))
    if file_count >= 2:
        score += min(file_count / 10.0, 0.2)

    # Tool diversity (0-0.15)
    unique_tools = len(set(tools_used))
    if unique_tools >= 2:
        score += min(unique_tools / 8.0, 0.15)

    # Has summary (0.15)
    if has_summary:
        score += 0.15

    return min(score, 1.0)


def _compute_description_hash(description: str) -> str:
    """Hash a description for duplicate detection."""
    normalized = " ".join(description.lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()


async def _count_todays_auto_skills(session: AsyncSession) -> int:
    """Count how many auto-generated skills were created today."""
    from datetime import date, datetime, timezone

    from src.storage.models import GeneratedSkillRecord

    today_start = datetime.combine(date.today(), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    result = await session.execute(
        select(func.count())
        .select_from(GeneratedSkillRecord)
        .where(
            GeneratedSkillRecord.source == "auto",
            GeneratedSkillRecord.created_at >= today_start,
        )
    )
    return result.scalar() or 0


async def _has_similar_skill(session: AsyncSession, description: str) -> bool:
    """Check if a similar skill already exists in the database."""
    from src.storage.models import GeneratedSkillRecord

    desc_hash = _compute_description_hash(description)

    result = await session.execute(
        select(func.count())
        .select_from(GeneratedSkillRecord)
        .where(
            GeneratedSkillRecord.skill_content_hash == desc_hash,
            GeneratedSkillRecord.is_active.is_(True),
        )
    )
    return (result.scalar() or 0) > 0


async def extract_skill_pattern(
    session: AsyncSession,
    agent_session: AgentSession,
) -> SkillContext:
    """Extract the repeatable pattern from a session for skill generation.

    Args:
        session: Database session.
        agent_session: The session to extract from.

    Returns:
        SkillContext with the extracted pattern.
    """
    # Collect data from turns
    files_touched: list[str] = []
    commands_run: list[str] = []
    tools_used: list[str] = []

    turns = await session.execute(
        select(AgentTurn)
        .where(AgentTurn.session_id == agent_session.id)
        .options(selectinload(AgentTurn.content))
        .order_by(AgentTurn.turn_number)
    )

    for turn in turns.scalars().all():
        if turn.tool_names:
            tools_used.extend(turn.tool_names)
        if turn.content:
            if turn.content.files_touched:
                files_touched.extend(turn.content.files_touched)
            if turn.content.commands_run:
                commands_run.extend(turn.content.commands_run)

    return SkillContext(
        workspace_path=agent_session.workspace_path or "",
        files_touched=list(set(files_touched)),
        commands_run=list(set(commands_run)),
        tools_used=list(set(tools_used)),
        session_summary=agent_session.session_summary or "",
    )


async def analyze_session_for_skill(
    session: AsyncSession,
    agent_session: AgentSession,
) -> Optional[SkillCandidate]:
    """Analyze a completed session to determine if it should become a skill.

    Args:
        session: Database session.
        agent_session: The completed AgentSession to analyze.

    Returns:
        SkillCandidate if the session qualifies, None otherwise.
    """
    settings = get_settings()

    if not settings.skills.auto_generate:
        return None

    if not agent_session.is_processed or not agent_session.session_summary:
        logger.debug("Session %s not fully processed, skipping", agent_session.session_id)
        return None

    # Check daily limit
    today_count = await _count_todays_auto_skills(session)
    if today_count >= settings.skills.max_auto_skills_per_day:
        logger.debug("Daily skill limit reached (%d), skipping", today_count)
        return None

    # Gather turn data for scoring
    turns = await session.execute(
        select(AgentTurn)
        .where(AgentTurn.session_id == agent_session.id)
        .options(selectinload(AgentTurn.content))
    )
    turn_list = turns.scalars().all()

    files_touched: list[str] = []
    tools_used: list[str] = []
    error_count = 0

    for turn in turn_list:
        if turn.tool_names:
            tools_used.extend(turn.tool_names)
        if turn.content:
            if turn.content.files_touched:
                files_touched.extend(turn.content.files_touched)
            if turn.content.errors_encountered:
                error_count += len(turn.content.errors_encountered)

    # Quality gate
    quality = score_session_quality(
        turn_count=len(turn_list),
        error_count=error_count,
        files_touched=files_touched,
        tools_used=tools_used,
        has_summary=bool(agent_session.session_summary),
    )

    if quality < settings.skills.min_quality_score:
        logger.debug(
            "Session %s quality %.2f below threshold %.2f",
            agent_session.session_id,
            quality,
            settings.skills.min_quality_score,
        )
        return None

    # Duplicate check
    description = agent_session.session_summary or ""
    if await _has_similar_skill(session, description):
        logger.debug("Similar skill already exists for session %s", agent_session.session_id)
        return None

    # Extract the pattern
    context = await extract_skill_pattern(session, agent_session)

    return SkillCandidate(
        session_id=agent_session.session_id,
        quality_score=quality,
        description=description,
        context=context,
        workspace_path=agent_session.workspace_path or "",
    )
