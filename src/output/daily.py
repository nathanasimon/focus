"""Daily note generation for the Obsidian vault."""

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import (
    Commitment,
    Email,
    EmailAccount,
    Project,
    Sprint,
    Task,
)

logger = logging.getLogger(__name__)


async def generate_daily_note(
    session: AsyncSession,
    vault_path: Path,
    target_date: Optional[date] = None,
) -> None:
    """Generate the daily note for a given date."""
    today = target_date or date.today()
    daily_dir = vault_path / "Daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    lines = [f"# {today.isoformat()}", ""]

    # Active sprint section
    await _add_sprint_section(session, lines, today)

    # Due this week
    await _add_due_this_week(session, lines, today)

    # Pinned projects
    await _add_pinned_projects(session, lines)

    # Needs reply
    await _add_needs_reply(session, lines)

    # Open commitments due soon
    await _add_commitments_due(session, lines, today)

    # Completed today section (placeholder)
    lines.extend([
        "## Completed Today",
        "_(auto-populated as tasks are marked done)_",
        "",
    ])

    (daily_dir / f"{today.isoformat()}.md").write_text("\n".join(lines) + "\n")
    logger.info("Generated daily note for %s", today)


async def _add_sprint_section(session: AsyncSession, lines: list[str], today: date) -> None:
    """Add active sprint info to daily note."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Sprint).where(
            Sprint.is_active.is_(True),
            Sprint.starts_at <= now,
            Sprint.ends_at >= now,
        )
    )
    sprints = result.scalars().all()

    for sprint in sprints:
        days_left = (sprint.ends_at.date() - today).days
        lines.append(f"## Active Sprint: {sprint.name} ({days_left} days left)")

        # Get tasks for this sprint's project
        if sprint.project_id:
            result = await session.execute(
                select(Task).where(
                    Task.project_id == sprint.project_id,
                    Task.status.in_(["backlog", "in_progress"]),
                ).order_by(Task.priority.asc())
            )
            tasks = result.scalars().all()
            for task in tasks:
                lines.append(f"- [ ] {task.title}")

        lines.append("")


async def _add_due_this_week(session: AsyncSession, lines: list[str], today: date) -> None:
    """Add tasks and projects due this week."""
    end_of_week = today + timedelta(days=(6 - today.weekday()))

    result = await session.execute(
        select(Task).where(
            Task.due_date.isnot(None),
            Task.due_date <= end_of_week,
            Task.status != "done",
        ).order_by(Task.due_date.asc())
    )
    tasks = result.scalars().all()

    result2 = await session.execute(
        select(Project).where(
            Project.user_deadline.isnot(None),
            Project.user_deadline <= end_of_week,
            Project.status == "active",
        ).order_by(Project.user_deadline.asc())
    )
    projects = result2.scalars().all()

    if tasks or projects:
        lines.append("## Due This Week")
        for task in tasks:
            lines.append(f"- [ ] {task.title} — due {task.due_date}")
        for project in projects:
            note = f" — {project.user_deadline_note}" if project.user_deadline_note else ""
            lines.append(f"- [ ] **{project.name}** — due {project.user_deadline}{note}")
        lines.append("")


async def _add_pinned_projects(session: AsyncSession, lines: list[str]) -> None:
    """Add pinned projects to daily note."""
    result = await session.execute(
        select(Project).where(
            Project.user_pinned.is_(True),
            Project.status == "active",
        )
    )
    pinned = result.scalars().all()

    if pinned:
        lines.append("## Pinned Projects")
        for project in pinned:
            desc = f" — {project.description[:80]}" if project.description else ""
            lines.append(f"- [[{project.name.replace(' ', '-')}]]{desc}")
        lines.append("")


async def _add_needs_reply(session: AsyncSession, lines: list[str]) -> None:
    """Add emails needing reply, sorted by priority."""
    result = await session.execute(
        select(Email, EmailAccount)
        .outerjoin(EmailAccount, Email.account_id == EmailAccount.id)
        .where(Email.needs_reply.is_(True), Email.reply_sent.is_(False))
        .order_by(Email.urgency.asc(), Email.email_date.asc())
        .limit(10)
    )
    rows = result.all()

    if rows:
        lines.append("## Needs Reply (by priority)")
        for email, account in rows:
            sender = (email.raw_headers or {}).get("from", "unknown")
            # Extract just the name part
            name = sender.split("<")[0].strip().strip('"')
            account_label = f"[{account.name}] " if account else ""
            urgency_label = email.urgency.upper() if email.urgency else "NORMAL"

            days_ago = ""
            if email.email_date:
                delta = (datetime.now(timezone.utc) - email.email_date).days
                days_ago = f"{delta} days, " if delta > 0 else "today, "

            lines.append(f"- {account_label}{name} — {email.subject or '(no subject)'} ({days_ago}{urgency_label})")
        lines.append("")


async def _add_commitments_due(session: AsyncSession, lines: list[str], today: date) -> None:
    """Add commitments due in the next 7 days."""
    next_week = today + timedelta(days=7)
    result = await session.execute(
        select(Commitment).where(
            Commitment.status == "open",
            Commitment.deadline.isnot(None),
            Commitment.deadline <= next_week,
        ).order_by(Commitment.deadline.asc())
    )
    commitments = result.scalars().all()

    if commitments:
        lines.append("## Commitments Due Soon")
        for c in commitments:
            direction = "I promised" if c.direction == "from_me" else "Promised to me"
            lines.append(f"- [ ] {direction}: {c.description} (due: {c.deadline})")
        lines.append("")
