"""Context retriever — queries PostgreSQL for relevant context based on classification."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.context.classifier import PromptClassification
from src.skills.installer import InstalledSkill, list_installed_skills, _parse_frontmatter
from src.storage.models import (
    AgentSession,
    AgentTurn,
    AgentTurnArtifact,
    AgentTurnContent,
    Commitment,
    Email,
    Person,
    Project,
    Sprint,
    Task,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextBlock:
    """A single block of context to inject."""

    source_type: str
    source_id: str
    title: str
    content: str
    relevance_score: float
    timestamp: Optional[datetime] = None
    token_estimate: int = 0

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = max(1, len(self.content) // 4)


class ContextRetriever:
    """Retrieves relevant context from Focus data stores.

    All queries are PostgreSQL — no LLM calls.
    """

    async def retrieve(
        self,
        session: AsyncSession,
        classification: PromptClassification,
        max_tokens: int = 1500,
    ) -> list[ContextBlock]:
        """Retrieve context blocks based on classification.

        Args:
            session: Database session.
            classification: The prompt classification result.
            max_tokens: Token budget for all context blocks combined.

        Returns:
            List of ContextBlocks sorted by relevance.
        """
        blocks: list[ContextBlock] = []

        if classification.confidence < 0.1:
            return blocks

        # Resolve project IDs
        project_ids: list[UUID] = []
        if classification.project_slugs:
            result = await session.execute(
                select(Project.id, Project.slug)
                .where(Project.slug.in_(classification.project_slugs))
            )
            project_ids = [row[0] for row in result.all()]
        elif classification.workspace_project:
            result = await session.execute(
                select(Project.id)
                .where(Project.slug == classification.workspace_project)
            )
            row = result.first()
            if row:
                project_ids = [row[0]]

        # Gather context from various sources
        if project_ids:
            for pid in project_ids:
                blocks.extend(await self._get_recent_turns(session, project_id=pid))
                blocks.extend(await self._get_active_tasks(session, project_id=pid))
                blocks.extend(await self._get_open_commitments(session, project_id=pid))

        if classification.workspace_project:
            # Always try workspace matching — supplements project-matched turns
            blocks.extend(await self._get_recent_turns(
                session, workspace_path_like=classification.workspace_project
            ))

        if not project_ids and not classification.workspace_project:
            # Global fallback: recent turns from any session
            blocks.extend(await self._get_recent_turns(session, limit=3))

        if classification.person_names:
            blocks.extend(await self._get_person_context(session, classification.person_names))

        # File-based context for code queries
        if classification.file_paths:
            blocks.extend(await self._get_turns_by_file(session, classification.file_paths))

        # Recent errors for debugging context
        if classification.query_type == "code" and project_ids:
            for pid in project_ids:
                blocks.extend(await self._get_recent_errors(session, project_id=pid))

        # Always include open commitments and active sprints
        if not project_ids:
            blocks.extend(await self._get_open_commitments(session))
        blocks.extend(await self._get_active_sprints(session))

        # Skill matching — disk I/O, no DB needed
        blocks.extend(self._get_relevant_skills(classification))

        # Deduplicate by source_id
        seen = set()
        unique_blocks = []
        for block in blocks:
            if block.source_id not in seen:
                seen.add(block.source_id)
                unique_blocks.append(block)

        # Sort by relevance
        unique_blocks.sort(key=lambda b: b.relevance_score, reverse=True)

        return unique_blocks

    async def _get_recent_turns(
        self,
        session: AsyncSession,
        project_id: Optional[UUID] = None,
        workspace_path_like: Optional[str] = None,
        limit: int = 5,
    ) -> list[ContextBlock]:
        """Query recent agent turn summaries.

        Args:
            session: Database session.
            project_id: Filter by project.
            workspace_path_like: Filter by workspace path pattern.
            limit: Max results.

        Returns:
            List of ContextBlocks.
        """
        query = (
            select(AgentTurn)
            .join(AgentSession)
            .options(selectinload(AgentTurn.session))
            .order_by(AgentTurn.started_at.desc().nulls_last())
            .limit(limit)
        )

        if project_id:
            query = query.where(AgentSession.project_id == project_id)
        elif workspace_path_like:
            query = query.where(AgentSession.workspace_path.ilike(f"%{workspace_path_like}%"))

        result = await session.execute(query)
        turns = result.scalars().all()

        blocks = []
        for turn in turns:
            title = turn.turn_title or (turn.user_message or "")[:60]
            content = turn.assistant_summary or (turn.user_message or "")[:150]
            age = _relative_time(turn.started_at)

            blocks.append(ContextBlock(
                source_type="conversation",
                source_id=str(turn.id),
                title=f"{title} ({age})",
                content=content,
                relevance_score=0.7,
                timestamp=turn.started_at,
            ))

        return blocks

    async def _get_active_tasks(
        self,
        session: AsyncSession,
        project_id: UUID,
        limit: int = 5,
    ) -> list[ContextBlock]:
        """Query active tasks for a project.

        Args:
            session: Database session.
            project_id: The project to query.
            limit: Max results.

        Returns:
            List of ContextBlocks.
        """
        result = await session.execute(
            select(Task)
            .where(
                Task.project_id == project_id,
                Task.status.in_(["in_progress", "waiting", "backlog"]),
            )
            .order_by(Task.status, Task.priority)
            .limit(limit)
        )
        tasks = result.scalars().all()

        blocks = []
        for task in tasks:
            due = f" (due {task.due_date})" if task.due_date else ""
            content = f"[{task.status}] {task.title}{due} | {task.priority}"

            blocks.append(ContextBlock(
                source_type="task",
                source_id=str(task.id),
                title=task.title,
                content=content,
                relevance_score=0.6 if task.status == "in_progress" else 0.4,
            ))

        return blocks

    async def _get_open_commitments(
        self,
        session: AsyncSession,
        project_id: Optional[UUID] = None,
        person_name: Optional[str] = None,
        limit: int = 3,
    ) -> list[ContextBlock]:
        """Query open commitments.

        Args:
            session: Database session.
            project_id: Filter by project.
            person_name: Filter by person name (unused for now, ID-based).
            limit: Max results.

        Returns:
            List of ContextBlocks.
        """
        query = (
            select(Commitment)
            .options(selectinload(Commitment.person))
            .where(Commitment.status == "open")
            .order_by(Commitment.deadline.asc().nulls_last())
            .limit(limit)
        )

        if project_id:
            query = query.where(Commitment.project_id == project_id)

        result = await session.execute(query)
        commitments = result.scalars().all()

        blocks = []
        for c in commitments:
            person_str = c.person.name if c.person else "unknown"
            direction = "from me to" if c.direction == "from_me" else "from"
            deadline = f" by {c.deadline}" if c.deadline else ""
            content = f"Commitment {direction} {person_str}: {c.description}{deadline}"

            blocks.append(ContextBlock(
                source_type="commitment",
                source_id=str(c.id),
                title=c.description[:60],
                content=content,
                relevance_score=0.5,
            ))

        return blocks

    async def _get_person_context(
        self,
        session: AsyncSession,
        person_names: list[str],
        limit: int = 3,
    ) -> list[ContextBlock]:
        """Get context about mentioned people.

        Args:
            session: Database session.
            person_names: Names to look up.
            limit: Max results per person.

        Returns:
            List of ContextBlocks.
        """
        blocks = []
        for name in person_names[:3]:
            result = await session.execute(
                select(Person).where(Person.name.ilike(f"%{name}%")).limit(1)
            )
            person = result.scalar_one_or_none()
            if not person:
                continue

            parts = [person.name]
            if person.organization:
                parts.append(f"({person.organization})")
            if person.relationship_type:
                parts.append(f"[{person.relationship_type}]")

            blocks.append(ContextBlock(
                source_type="person",
                source_id=str(person.id),
                title=person.name,
                content=" ".join(parts),
                relevance_score=0.5,
            ))

        return blocks

    async def _get_turns_by_file(
        self,
        session: AsyncSession,
        file_paths: list[str],
        limit: int = 3,
    ) -> list[ContextBlock]:
        """Find prior turns that touched specific files.

        Args:
            session: Database session.
            file_paths: File paths to search for.
            limit: Max results.

        Returns:
            List of ContextBlocks for turns that touched those files.
        """
        from sqlalchemy import any_

        blocks = []
        for path in file_paths[:5]:
            result = await session.execute(
                select(AgentTurn)
                .join(AgentTurnContent, AgentTurn.id == AgentTurnContent.turn_id)
                .where(AgentTurnContent.files_touched.any(path))
                .order_by(AgentTurn.started_at.desc().nulls_last())
                .limit(limit)
            )
            turns = result.scalars().all()

            for turn in turns:
                title = turn.turn_title or (turn.user_message or "")[:60]
                content = f"Previously touched {path}: {turn.assistant_summary or turn.user_message or ''}".strip()[:200]

                blocks.append(ContextBlock(
                    source_type="file_context",
                    source_id=f"file:{turn.id}:{path}",
                    title=f"File: {path.split('/')[-1]}",
                    content=content,
                    relevance_score=0.65,
                    timestamp=turn.started_at,
                ))

        return blocks

    async def _get_recent_errors(
        self,
        session: AsyncSession,
        project_id: Optional[UUID] = None,
        limit: int = 3,
    ) -> list[ContextBlock]:
        """Get recent errors from conversation turns.

        Args:
            session: Database session.
            project_id: Filter by project.
            limit: Max results.

        Returns:
            List of ContextBlocks for recent errors.
        """
        query = (
            select(AgentTurn)
            .join(AgentTurnContent, AgentTurn.id == AgentTurnContent.turn_id)
            .where(AgentTurnContent.errors_encountered.isnot(None))
            .order_by(AgentTurn.started_at.desc().nulls_last())
            .limit(limit)
        )

        if project_id:
            query = query.join(AgentSession).where(AgentSession.project_id == project_id)

        result = await session.execute(query)
        turns = result.scalars().all()

        blocks = []
        for turn in turns:
            title = turn.turn_title or "Error encountered"
            age = _relative_time(turn.started_at)

            blocks.append(ContextBlock(
                source_type="error",
                source_id=f"error:{turn.id}",
                title=f"{title} ({age})",
                content=f"Errors in previous session: {turn.user_message or ''}".strip()[:200],
                relevance_score=0.55,
                timestamp=turn.started_at,
            ))

        return blocks

    async def _get_active_sprints(
        self,
        session: AsyncSession,
    ) -> list[ContextBlock]:
        """Get active sprint info.

        Args:
            session: Database session.

        Returns:
            List of ContextBlocks for active sprints.
        """
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(Sprint)
            .options(selectinload(Sprint.project))
            .where(Sprint.is_active.is_(True), Sprint.ends_at > now)
            .limit(3)
        )
        sprints = result.scalars().all()

        blocks = []
        for sprint in sprints:
            days_left = (sprint.ends_at.replace(tzinfo=timezone.utc) - now).days if sprint.ends_at else 0
            project_name = sprint.project.name if sprint.project else "no project"
            content = f"Sprint: {sprint.name} ({project_name}, {days_left}d left)"

            blocks.append(ContextBlock(
                source_type="sprint",
                source_id=str(sprint.id),
                title=sprint.name,
                content=content,
                relevance_score=0.3,
            ))

        return blocks


    def _get_relevant_skills(
        self,
        classification: PromptClassification,
        max_skills: int = 3,
    ) -> list[ContextBlock]:
        """Match installed skills against the current prompt classification.

        Pure disk I/O + keyword matching — no LLM or DB calls.
        Reads SKILL.md files, matches name/description against prompt keywords.

        Args:
            classification: The prompt classification result.
            max_skills: Maximum number of skills to return.

        Returns:
            List of ContextBlocks for relevant skills.
        """
        try:
            cwd = Path(classification.workspace_project).resolve() if classification.workspace_project else None
        except (TypeError, ValueError):
            cwd = None

        # Scan both personal and project-scoped skills
        skills = list_installed_skills(scope="all", project_path=cwd)
        if not skills:
            return []

        # Build keyword set from prompt classification
        prompt_words = set()
        for slug in classification.project_slugs:
            prompt_words.update(slug.lower().split("-"))
        for name in classification.person_names:
            prompt_words.update(name.lower().split())
        if classification.workspace_project:
            prompt_words.update(classification.workspace_project.lower().split("-"))
        if classification.query_type != "general":
            prompt_words.add(classification.query_type)
        for path in classification.file_paths:
            # Extract filename without extension
            stem = Path(path).stem.lower()
            prompt_words.update(re.split(r"[_\-.]", stem))

        # Filter out very short/common words
        prompt_words = {w for w in prompt_words if len(w) > 2}

        if not prompt_words:
            return []

        scored: list[tuple[float, InstalledSkill, str]] = []
        for skill in skills:
            score, body = _score_skill_relevance(skill, prompt_words)
            if score > 0:
                scored.append((score, skill, body))

        # Sort by score descending, take top N
        scored.sort(key=lambda x: x[0], reverse=True)

        blocks = []
        for score, skill, body in scored[:max_skills]:
            # Include skill body (instructions) truncated to stay within budget
            content = _format_skill_content(skill, body)
            blocks.append(ContextBlock(
                source_type="skill",
                source_id=f"skill:{skill.name}",
                title=f"Skill: {skill.name}",
                content=content,
                relevance_score=min(0.85, 0.5 + score * 0.35),
            ))

        return blocks


def _score_skill_relevance(
    skill: InstalledSkill,
    prompt_words: set[str],
) -> tuple[float, str]:
    """Score how relevant a skill is to the current prompt.

    Args:
        skill: The installed skill to score.
        prompt_words: Set of lowercase keywords from the prompt classification.

    Returns:
        Tuple of (relevance_score 0.0-1.0, skill body text).
    """
    # Build the skill's keyword set from name + description + body
    skill_words = set()
    skill_words.update(re.split(r"[_\-\s]+", skill.name.lower()))
    if skill.description:
        skill_words.update(re.split(r"[\s,.\-_]+", skill.description.lower()))

    # Read body for deeper matching
    body = ""
    try:
        body = skill.path.read_text()
    except (OSError, IOError):
        pass

    if body:
        # Extract body after frontmatter
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body_text = parts[2].strip()
        else:
            body_text = body
        # Add first ~200 words from body to keyword set
        body_words = re.split(r"[\s,.\-_:;()]+", body_text.lower())[:200]
        skill_words.update(w for w in body_words if len(w) > 2)

    # Filter out common/short words
    skill_words = {w for w in skill_words if len(w) > 2}

    if not skill_words:
        return 0.0, body

    # Compute overlap
    overlap = prompt_words & skill_words
    if not overlap:
        return 0.0, body

    # Score: fraction of prompt words that matched, weighted by total matches
    coverage = len(overlap) / len(prompt_words)
    # Bonus for name match (skill name directly matches a prompt keyword)
    name_parts = set(re.split(r"[_\-]+", skill.name.lower()))
    name_overlap = prompt_words & name_parts
    name_bonus = 0.3 if name_overlap else 0.0

    score = min(1.0, coverage + name_bonus)
    return score, body


def _format_skill_content(skill: InstalledSkill, raw_content: str) -> str:
    """Format skill content for context injection.

    Includes the skill description and a truncated body.

    Args:
        skill: The installed skill.
        raw_content: Raw SKILL.md content from disk.

    Returns:
        Formatted content string.
    """
    parts = [skill.description] if skill.description else []

    # Extract body after frontmatter
    if raw_content:
        sections = raw_content.split("---", 2)
        if len(sections) >= 3:
            body = sections[2].strip()
        else:
            body = raw_content.strip()

        # Truncate body to ~300 chars
        if len(body) > 300:
            body = body[:297] + "..."
        parts.append(body)

    parts.append(f"(full instructions: {skill.path})")
    return " | ".join(parts)


def _relative_time(dt: Optional[datetime]) -> str:
    """Format a datetime as a relative time string.

    Args:
        dt: The datetime to format.

    Returns:
        Human-readable relative time (e.g., "2h ago", "3d ago").
    """
    if not dt:
        return "unknown time"

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        return f"{seconds // 3600}h ago"
    elif seconds < 604800:
        return f"{seconds // 86400}d ago"
    else:
        return f"{seconds // 604800}w ago"
