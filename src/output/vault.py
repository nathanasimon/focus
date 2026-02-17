"""Obsidian vault generator — radically simple, focused on what matters now."""

import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.storage.models import (
    Commitment,
    Email,
    EmailAccount,
    Person,
    Project,
    ProjectPeople,
    Sprint,
    Task,
)

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


async def generate_vault(session: AsyncSession, vault_path: Optional[Path] = None) -> None:
    """Generate the full Obsidian vault from current DB state."""
    settings = get_settings()
    vault = Path(vault_path or settings.general.vault_path).expanduser()

    logger.info("Generating vault at %s", vault)

    _ensure_dir(vault)
    _ensure_dir(vault / "Projects")
    _ensure_dir(vault / "People")
    _ensure_dir(vault / "Daily")

    await _generate_today(session, vault)
    await _generate_inbox(session, vault)
    await _generate_drafts(session, vault)
    await _generate_projects(session, vault)
    await _generate_people(session, vault)
    await _generate_commitments(session, vault)

    logger.info("Vault generation complete")


# ---------------------------------------------------------------------------
# TODAY.md — the single most important file
# ---------------------------------------------------------------------------

async def _generate_today(session: AsyncSession, vault: Path) -> None:
    """Generate TODAY.md — what matters right now."""
    today = date.today()
    now = datetime.now(timezone.utc)
    lines = [f"# {today.strftime('%A, %B %d')}", ""]

    # Active sprints
    result = await session.execute(
        select(Sprint).where(
            Sprint.is_active.is_(True),
            Sprint.starts_at <= now,
            Sprint.ends_at >= now,
        )
    )
    for sprint in result.scalars().all():
        days_left = (sprint.ends_at.date() - today).days
        lines.append(f"**Sprint: {sprint.name}** — {days_left} days left")
        lines.append("")

    # Urgent emails needing reply
    result = await session.execute(
        select(Email)
        .options(selectinload(Email.account))
        .where(
            Email.needs_reply.is_(True),
            Email.reply_sent.is_(False),
            Email.classification == "human",
        )
        .order_by(Email.urgency.asc(), Email.email_date.asc())
        .limit(10)
    )
    reply_emails = result.scalars().all()
    if reply_emails:
        lines.append("## Reply to")
        for email in reply_emails:
            sender = _sender_name(email)
            age = _age_str(email.email_date)
            urgency = " **URGENT**" if email.urgency == "urgent" else ""
            lines.append(f"- {sender} — {email.subject or '(no subject)'}{urgency} ({age})")
        lines.append("")

    # Tasks due this week
    end_of_week = today + timedelta(days=(6 - today.weekday()))
    result = await session.execute(
        select(Task).where(
            Task.due_date.isnot(None),
            Task.due_date <= end_of_week,
            Task.status != "done",
        ).order_by(Task.due_date.asc())
    )
    due_tasks = result.scalars().all()
    if due_tasks:
        lines.append("## Due this week")
        for task in due_tasks:
            lines.append(f"- [ ] {task.title} — {task.due_date}")
        lines.append("")

    # In-progress tasks
    result = await session.execute(
        select(Task).where(Task.status == "in_progress").order_by(Task.created_at.asc())
    )
    active_tasks = result.scalars().all()
    if active_tasks:
        lines.append("## In progress")
        for task in active_tasks:
            lines.append(f"- [ ] {task.title}")
        lines.append("")

    # Commitments due within 7 days
    next_week = today + timedelta(days=7)
    result = await session.execute(
        select(Commitment)
        .options(selectinload(Commitment.person))
        .where(
            Commitment.status == "open",
            Commitment.deadline.isnot(None),
            Commitment.deadline <= next_week,
        ).order_by(Commitment.deadline.asc())
    )
    due_commitments = result.scalars().all()
    if due_commitments:
        lines.append("## Commitments due")
        for c in due_commitments:
            who = f" ({c.person.name})" if c.person else ""
            direction = "I owe" if c.direction == "from_me" else "Owed to me"
            lines.append(f"- {direction}{who}: {c.description} — {c.deadline}")
        lines.append("")

    # Waiting on others
    result = await session.execute(
        select(Task).where(Task.status == "waiting")
    )
    waiting = result.scalars().all()
    if waiting:
        lines.append("## Waiting on")
        for task in waiting:
            days = ""
            if task.waiting_since:
                d = (now - task.waiting_since).days
                days = f" ({d}d)"
            lines.append(f"- {task.title}{days}")
        lines.append("")

    # Only write if there's actual content beyond the header
    if len(lines) > 2:
        (vault / "TODAY.md").write_text("\n".join(lines) + "\n")
    else:
        lines.append("Nothing pressing. Good day to do deep work.")
        lines.append("")
        (vault / "TODAY.md").write_text("\n".join(lines) + "\n")

    # Also write to Daily archive
    daily_dir = vault / "Daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / f"{today.isoformat()}.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# INBOX.md — only human emails that need attention
# ---------------------------------------------------------------------------

async def _generate_inbox(session: AsyncSession, vault: Path) -> None:
    """Generate INBOX.md — only actionable human emails."""
    result = await session.execute(
        select(Email)
        .options(selectinload(Email.account))
        .where(
            Email.classification == "human",
            Email.extraction_result.isnot(None),
        )
        .order_by(Email.email_date.desc())
        .limit(30)
    )
    emails = result.scalars().all()
    if not emails:
        return

    lines = ["# Inbox", ""]

    needs_reply = [e for e in emails if e.needs_reply and not e.reply_sent]
    rest = [e for e in emails if not (e.needs_reply and not e.reply_sent)]

    if needs_reply:
        lines.append("## Needs reply")
        for email in needs_reply:
            _format_inbox_email(lines, email)

    if rest:
        lines.append("## Recent")
        for email in rest[:15]:
            _format_inbox_email(lines, email)

    (vault / "INBOX.md").write_text("\n".join(lines) + "\n")


def _format_inbox_email(lines: list[str], email: Email) -> None:
    """Format a single inbox email entry."""
    sender = _sender_name(email)
    age = _age_str(email.email_date)
    urgency = " **URGENT**" if email.urgency == "urgent" else ""

    lines.append(f"### {sender} — {email.subject or '(no subject)'}{urgency}")
    lines.append(f"*{age}*")

    if email.snippet:
        lines.append(f"> {email.snippet[:300]}")

    ext = email.extraction_result or {}
    tasks = ext.get("tasks", [])
    if tasks:
        lines.append("")
        for t in tasks[:3]:
            lines.append(f"- [ ] {t.get('text', '')}")

    if email.reply_suggested:
        lines.append(f"\n**Draft reply**: {email.reply_suggested}")

    lines.append("")


# ---------------------------------------------------------------------------
# DRAFTS.md — suggested replies
# ---------------------------------------------------------------------------

async def _generate_drafts(session: AsyncSession, vault: Path) -> None:
    """Generate DRAFTS.md — suggested replies ready to send."""
    result = await session.execute(
        select(Email)
        .options(selectinload(Email.account))
        .where(
            Email.needs_reply.is_(True),
            Email.reply_sent.is_(False),
            Email.reply_suggested.isnot(None),
            Email.classification == "human",
        )
        .order_by(Email.urgency.asc(), Email.email_date.asc())
    )
    emails = result.scalars().all()
    if not emails:
        return

    lines = ["# Drafts", ""]

    for email in emails:
        sender = _sender_name(email)
        age = _age_str(email.email_date)
        lines.append(f"### Re: {email.subject or '(no subject)'}")
        lines.append(f"To: {sender} ({age})")
        lines.append("")
        lines.append(f"> {email.reply_suggested}")
        lines.append("")
        lines.append("---")
        lines.append("")

    (vault / "DRAFTS.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Projects — one file per project, everything on one page
# ---------------------------------------------------------------------------

async def _generate_projects(session: AsyncSession, vault: Path) -> None:
    """Generate one file per active project with tasks, people, and emails inline."""
    projects_dir = _ensure_dir(vault / "Projects")

    result = await session.execute(
        select(Project)
        .where(Project.status.in_(["active", "paused"]))
        .order_by(Project.last_activity.desc().nullslast())
    )
    projects = result.scalars().all()

    for project in projects:
        content = await _build_project_page(session, project)
        safe_name = project.name.replace(" ", "-")
        (projects_dir / f"{safe_name}.md").write_text(content)


async def _build_project_page(session: AsyncSession, project: Project) -> str:
    """Build a single project page with everything inline."""
    lines = [f"# {project.name}"]
    if project.description:
        lines.append(f"> {project.description}")
    lines.append("")

    status = project.status.title()
    if project.user_pinned:
        status += " | PINNED"
    if project.user_deadline:
        note = f" — {project.user_deadline_note}" if project.user_deadline_note else ""
        status += f" | Due: {project.user_deadline}{note}"
    lines.append(f"*{status}*")
    lines.append("")

    # Tasks
    result = await session.execute(
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.created_at.asc())
    )
    tasks = result.scalars().all()

    in_progress = [t for t in tasks if t.status == "in_progress"]
    waiting = [t for t in tasks if t.status == "waiting"]
    backlog = [t for t in tasks if t.status == "backlog"]
    done = [t for t in tasks if t.status == "done"]

    if in_progress or waiting or backlog:
        lines.append("## Tasks")
        if in_progress:
            for t in in_progress:
                due = f" — due {t.due_date}" if t.due_date else ""
                lines.append(f"- [ ] **{t.title}**{due}")
        if waiting:
            for t in waiting:
                days = ""
                if t.waiting_since:
                    d = (datetime.now(timezone.utc) - t.waiting_since).days
                    days = f" ({d}d waiting)"
                lines.append(f"- [ ] {t.title} *waiting*{days}")
        if backlog:
            for t in backlog:
                due = f" — due {t.due_date}" if t.due_date else ""
                lines.append(f"- [ ] {t.title}{due}")
        if done:
            cutoff = datetime.now(timezone.utc).timestamp() - (14 * 86400)
            recent = [t for t in done if t.completed_at and t.completed_at.timestamp() > cutoff]
            if recent:
                lines.append("")
                for t in recent:
                    lines.append(f"- [x] ~~{t.title}~~")
        lines.append("")

    # People
    result = await session.execute(
        select(Person, ProjectPeople.role)
        .join(ProjectPeople, ProjectPeople.person_id == Person.id)
        .where(ProjectPeople.project_id == project.id)
    )
    people = result.all()
    if people:
        lines.append("## People")
        for person, role in people:
            role_str = f" ({role})" if role else ""
            lines.append(f"- [[{person.name.replace(' ', '-')}]]{role_str}")
        lines.append("")

    # Recent emails about this project
    result = await session.execute(
        select(Email)
        .where(
            Email.classification == "human",
            Email.extraction_result.isnot(None),
        )
        .order_by(Email.email_date.desc())
        .limit(50)
    )
    all_emails = result.scalars().all()
    project_emails = []
    for email in all_emails:
        ext = email.extraction_result or {}
        links = [l.lower() for l in ext.get("project_links", [])]
        if project.slug.lower() in links or project.name.lower() in links:
            project_emails.append(email)

    if project_emails:
        lines.append("## Recent emails")
        for email in project_emails[:10]:
            sender = _sender_name(email)
            date_str = email.email_date.strftime("%b %d") if email.email_date else "?"
            lines.append(f"- **{sender}** {date_str} — {email.subject or '(no subject)'}")
            if email.snippet:
                lines.append(f"  > {email.snippet[:150]}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# People — who they are and what's happening
# ---------------------------------------------------------------------------

async def _generate_people(session: AsyncSession, vault: Path) -> None:
    """Generate person files — only for people with actual interactions."""
    people_dir = _ensure_dir(vault / "People")

    result = await session.execute(
        select(Person).order_by(Person.last_contact.desc().nullslast())
    )
    people = result.scalars().all()

    for person in people:
        content = await _build_person_page(session, person)
        safe_name = person.name.replace(" ", "-")
        (people_dir / f"{safe_name}.md").write_text(content)


async def _build_person_page(session: AsyncSession, person: Person) -> str:
    """Build a person page with context about what you're doing with them."""
    lines = [f"# {person.name}"]

    meta = []
    if person.email:
        meta.append(person.email)
    if person.organization:
        meta.append(person.organization)
    if person.relationship_type and person.relationship_type != "unknown":
        meta.append(person.relationship_type)
    if meta:
        lines.append(f"*{' | '.join(meta)}*")
    lines.append("")

    # Shared projects
    result = await session.execute(
        select(Project, ProjectPeople.role)
        .join(ProjectPeople, ProjectPeople.project_id == Project.id)
        .where(ProjectPeople.person_id == person.id, Project.status == "active")
    )
    projects = result.all()
    if projects:
        lines.append("## Projects together")
        for proj, role in projects:
            role_str = f" ({role})" if role else ""
            lines.append(f"- [[{proj.name.replace(' ', '-')}]]{role_str}")
        lines.append("")

    # Open commitments involving this person
    result = await session.execute(
        select(Commitment).where(
            Commitment.person_id == person.id,
            Commitment.status == "open",
        ).order_by(Commitment.deadline.asc().nullslast())
    )
    commitments = result.scalars().all()
    if commitments:
        lines.append("## Open commitments")
        for c in commitments:
            direction = "I owe them" if c.direction == "from_me" else "They owe me"
            deadline = f" — due {c.deadline}" if c.deadline else ""
            lines.append(f"- {direction}: {c.description}{deadline}")
        lines.append("")

    # Recent emails from/about this person
    if person.email:
        email_pattern = f"%{person.email}%"
        result = await session.execute(
            select(Email)
            .where(Email.classification == "human")
            .order_by(Email.email_date.desc())
            .limit(50)
        )
        all_emails = result.scalars().all()
        person_emails = [
            e for e in all_emails
            if person.email.lower() in (e.raw_headers or {}).get("from", "").lower()
        ]
        if person_emails:
            lines.append("## Recent")
            for email in person_emails[:5]:
                date_str = email.email_date.strftime("%b %d") if email.email_date else "?"
                lines.append(f"- {date_str} — {email.subject or '(no subject)'}")
                if email.snippet:
                    lines.append(f"  > {email.snippet[:150]}")
            lines.append("")

    if person.notes:
        lines.append("## Notes")
        lines.append(person.notes)
        lines.append("")

    # Contact timeline
    contact = []
    if person.first_contact:
        contact.append(f"First: {person.first_contact.strftime('%Y-%m-%d')}")
    if person.last_contact:
        contact.append(f"Last: {person.last_contact.strftime('%Y-%m-%d')}")
    if contact:
        lines.append(f"*{' | '.join(contact)}*")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Commitments.md
# ---------------------------------------------------------------------------

async def _generate_commitments(session: AsyncSession, vault: Path) -> None:
    """Generate Commitments.md — what you owe and what's owed to you."""
    result = await session.execute(
        select(Commitment)
        .options(selectinload(Commitment.person))
        .where(Commitment.status == "open")
        .order_by(Commitment.deadline.asc().nullslast())
    )
    commitments = result.scalars().all()
    if not commitments:
        return

    lines = ["# Commitments", ""]

    from_me = [c for c in commitments if c.direction == "from_me"]
    to_me = [c for c in commitments if c.direction == "to_me"]

    if from_me:
        lines.append("## I owe")
        for c in from_me:
            who = f" ({c.person.name})" if c.person else ""
            deadline = f" — due {c.deadline}" if c.deadline else ""
            lines.append(f"- [ ] {c.description}{who}{deadline}")
        lines.append("")

    if to_me:
        lines.append("## Owed to me")
        for c in to_me:
            who = f" ({c.person.name})" if c.person else ""
            deadline = f" — due {c.deadline}" if c.deadline else ""
            lines.append(f"- [ ] {c.description}{who}{deadline}")
        lines.append("")

    (vault / "Commitments.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sender_name(email: Email) -> str:
    """Extract just the human name from a From: header."""
    sender = (email.raw_headers or {}).get("from", "unknown")
    name = sender.split("<")[0].strip().strip('"').strip()
    return name or sender


def _age_str(email_date: Optional[datetime]) -> str:
    """Human-readable age string for an email."""
    if not email_date:
        return "unknown date"
    days = (datetime.now(timezone.utc) - email_date).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks}w ago"
    return email_date.strftime("%b %d")
