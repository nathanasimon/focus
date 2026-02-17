"""User priority system — effective priority calculation."""

import logging
from datetime import date, datetime, timedelta, timezone
from math import log
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import EmailAccount, Project, Sprint, Task

logger = logging.getLogger(__name__)


async def get_active_sprint_for(
    session: AsyncSession,
    project_id: Optional[UUID],
    now: Optional[datetime] = None,
) -> Optional[Sprint]:
    """Get the active sprint for a project, if any."""
    if not project_id:
        return None
    now = now or datetime.now(timezone.utc)
    result = await session.execute(
        select(Sprint).where(
            Sprint.project_id == project_id,
            Sprint.is_active.is_(True),
            Sprint.starts_at <= now,
            Sprint.ends_at >= now,
        )
    )
    return result.scalar_one_or_none()


async def effective_priority_project(
    session: AsyncSession,
    project: Project,
    now: Optional[datetime] = None,
) -> float:
    """Calculate effective priority score for a project."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    score = 0.0

    # 1. User override (highest weight)
    if project.user_pinned:
        score += 100
    if project.user_priority:
        score += {"critical": 80, "high": 40, "normal": 0, "low": -20}.get(project.user_priority, 0)

    # 2. Temporal urgency
    deadline = project.user_deadline
    if deadline:
        days_left = (deadline - today).days
        if days_left <= 0:
            score += 90
        elif days_left <= 3:
            score += 70
        elif days_left <= 7:
            score += 40
        elif days_left <= 14:
            score += 20
        else:
            score += 5

    # 3. Active sprint boost
    sprint = await get_active_sprint_for(session, project.id, now)
    if sprint:
        # Guarantee minimum elevation so sprints always matter, even on zero base
        score = max(score, 10.0) * sprint.priority_boost

    # 4. Activity signals (low weight)
    if project.mention_count > 0:
        score += log(project.mention_count + 1) * 2
    score += project.source_diversity * 3
    score += project.people_count * 1.5

    return score


async def effective_priority_task(
    session: AsyncSession,
    task: Task,
    now: Optional[datetime] = None,
) -> float:
    """Calculate effective priority score for a task."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    score = 0.0

    # 1. User override
    if task.user_pinned:
        score += 100
    if task.user_priority:
        score += {"urgent": 80, "high": 40, "normal": 0, "low": -20}.get(task.user_priority, 0)

    # 2. Base priority
    score += {"urgent": 30, "high": 15, "normal": 0, "low": -10}.get(task.priority, 0)

    # 3. Temporal urgency
    deadline = task.due_date
    if deadline:
        days_left = (deadline - today).days
        if days_left <= 0:
            score += 90
        elif days_left <= 3:
            score += 70
        elif days_left <= 7:
            score += 40
        elif days_left <= 14:
            score += 20
        else:
            score += 5

    # 4. Active sprint boost
    sprint = await get_active_sprint_for(session, task.project_id, now)
    if sprint:
        score = max(score, 10.0) * sprint.priority_boost

    # 5. Account weight
    if task.source_account_id:
        account = await session.get(EmailAccount, task.source_account_id)
        if account:
            score *= account.priority_weight

    return score


async def get_priority_ranking(
    session: AsyncSession,
    scope: str = "all",  # "all", "today", "week"
    now: Optional[datetime] = None,
) -> list[dict]:
    """Get projects ranked by effective priority.

    Args:
        scope: "all", "today" (deadlines today), or "week" (deadlines this week)
        now: Override current time for testing
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()

    query = select(Project).where(Project.status == "active")
    result = await session.execute(query)
    projects = result.scalars().all()

    ranked = []
    for project in projects:
        score = await effective_priority_project(session, project, now)
        ranked.append({
            "project": project,
            "score": score,
            "name": project.name,
            "slug": project.slug,
            "deadline": project.user_deadline,
            "pinned": project.user_pinned,
            "priority": project.user_priority,
        })

    # Filter by scope
    if scope == "today":
        ranked = [r for r in ranked if r["deadline"] == today or r["pinned"]]
    elif scope == "week":
        end_of_week = today + timedelta(days=(6 - today.weekday()))
        ranked = [r for r in ranked if (r["deadline"] and r["deadline"] <= end_of_week) or r["pinned"]]

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


async def expire_sprints(session: AsyncSession) -> list[str]:
    """Check for expired sprints and deactivate them.

    Returns list of expired sprint names.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Sprint).where(
            Sprint.is_active.is_(True),
            Sprint.ends_at < now,
        )
    )
    expired = result.scalars().all()

    expired_names = []
    for sprint in expired:
        sprint.is_active = False
        expired_names.append(sprint.name)

        # Auto-archive project if configured
        if sprint.auto_archive_project and sprint.project_id:
            project = await session.get(Project, sprint.project_id)
            if project:
                project.status = "completed"
                logger.info("Auto-archived project %s after sprint %s expired", project.name, sprint.name)

    if expired_names:
        await session.flush()
        logger.info("Expired sprints: %s", ", ".join(expired_names))

    return expired_names
