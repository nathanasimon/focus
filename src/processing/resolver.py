"""Entity resolution — fuzzy-match people and projects across sources."""

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import (
    Commitment,
    Email,
    Person,
    Project,
    ProjectPeople,
    Task,
)

logger = logging.getLogger(__name__)

# Similarity thresholds
PERSON_NAME_THRESHOLD = 0.8
PERSON_EMAIL_THRESHOLD = 0.9
PROJECT_NAME_THRESHOLD = 0.7


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison."""
    return re.sub(r"[^a-z\s]", "", name.lower()).strip()


def _similarity(a: str, b: str) -> float:
    """Compute string similarity ratio."""
    return SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def _extract_email_from_header(from_header: str) -> Optional[str]:
    """Extract email address from a From: header."""
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", from_header)
    return match.group(0).lower() if match else None


def _extract_name_from_header(from_header: str) -> Optional[str]:
    """Extract display name from a From: header."""
    # "John Doe <john@example.com>" -> "John Doe"
    match = re.match(r'^"?([^"<]+)"?\s*<', from_header)
    if match:
        return match.group(1).strip()
    # Fallback: use the part before @
    email = _extract_email_from_header(from_header)
    if email:
        return email.split("@")[0].replace(".", " ").title()
    return None


def _slugify(name: str) -> str:
    """Convert a name to a URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed-project"


async def resolve_person(
    session: AsyncSession,
    name: Optional[str] = None,
    email: Optional[str] = None,
    organization: Optional[str] = None,
) -> Person:
    """Find or create a person, using fuzzy matching.

    Matching priority:
    1. Exact email match
    2. Fuzzy name match above threshold
    3. Create new person
    """
    # 1. Try exact email match
    if email:
        email_lower = email.lower()
        result = await session.execute(
            select(Person).where(func.lower(Person.email) == email_lower)
        )
        if found := result.scalar_one_or_none():
            # Update last_contact
            found.last_contact = datetime.now(timezone.utc)
            if name and not found.name:
                found.name = name
            return found

    # 2. Try fuzzy name match
    if name:
        result = await session.execute(select(Person))
        existing_people = result.scalars().all()

        best_match = None
        best_score = 0.0
        for person in existing_people:
            score = _similarity(name, person.name)
            if score > best_score and score >= PERSON_NAME_THRESHOLD:
                best_match = person
                best_score = score

        if best_match:
            best_match.last_contact = datetime.now(timezone.utc)
            if email and not best_match.email:
                best_match.email = email
            return best_match

    # 3. Create new person
    display_name = name or (email.split("@")[0].replace(".", " ").title() if email else "Unknown")
    person = Person(
        name=display_name,
        email=email,
        organization=organization,
        first_contact=datetime.now(timezone.utc),
        last_contact=datetime.now(timezone.utc),
        relationship_type="unknown",
    )
    session.add(person)
    await session.flush()
    logger.info("Created new person: %s (%s)", display_name, email or "no email")
    return person


async def resolve_person_from_email_header(
    session: AsyncSession,
    from_header: str,
) -> Person:
    """Resolve a person from an email From: header."""
    email = _extract_email_from_header(from_header)
    name = _extract_name_from_header(from_header)
    return await resolve_person(session, name=name, email=email)


async def resolve_project(
    session: AsyncSession,
    name: str,
    description: Optional[str] = None,
) -> Project:
    """Find or create a project, using fuzzy matching.

    Matching priority:
    1. Exact slug match
    2. Fuzzy name match above threshold
    3. Create new project
    """
    slug = _slugify(name)

    # 1. Try exact slug match
    result = await session.execute(
        select(Project).where(Project.slug == slug)
    )
    if found := result.scalar_one_or_none():
        found.last_activity = datetime.now(timezone.utc)
        found.mention_count += 1
        return found

    # 2. Try fuzzy name match
    result = await session.execute(select(Project).where(Project.status == "active"))
    existing = result.scalars().all()

    for project in existing:
        if _similarity(name, project.name) >= PROJECT_NAME_THRESHOLD:
            project.last_activity = datetime.now(timezone.utc)
            project.mention_count += 1
            return project

    # 3. Create new project
    project = Project(
        name=name,
        slug=slug,
        description=description,
        first_mention=datetime.now(timezone.utc),
        last_activity=datetime.now(timezone.utc),
        mention_count=1,
    )
    session.add(project)
    await session.flush()
    logger.info("Created new project: %s (%s)", name, slug)
    return project


async def link_person_to_project(
    session: AsyncSession,
    person_id: UUID,
    project_id: UUID,
    role: Optional[str] = None,
) -> None:
    """Link a person to a project (idempotent)."""
    existing = await session.execute(
        select(ProjectPeople).where(
            ProjectPeople.project_id == project_id,
            ProjectPeople.person_id == person_id,
        )
    )
    if not existing.scalar_one_or_none():
        link = ProjectPeople(
            project_id=project_id,
            person_id=person_id,
            role=role,
        )
        session.add(link)
        await session.flush()


async def resolve_extraction(
    session: AsyncSession,
    email: Email,
    extraction: dict,
) -> dict:
    """Resolve all entities mentioned in an extraction result.

    Creates/links people, projects, tasks, and commitments.
    Returns a summary of what was resolved.
    """
    resolved = {
        "people": [],
        "projects": [],
        "tasks_created": 0,
        "commitments_created": 0,
    }

    # Resolve sender
    sender_header = (email.raw_headers or {}).get("from", "")
    if sender_header:
        sender = await resolve_person_from_email_header(session, sender_header)
        email.sender_id = sender.id
        resolved["people"].append(sender.name)

    # Resolve mentioned people
    for person_name in extraction.get("people_mentioned", []):
        person = await resolve_person(session, name=person_name)
        resolved["people"].append(person.name)

    # Resolve project links
    for project_slug in extraction.get("project_links", []):
        project = await resolve_project(session, name=project_slug)
        resolved["projects"].append(project.slug)

        # Link sender to project
        if email.sender_id:
            await link_person_to_project(session, email.sender_id, project.id)

    # Create new projects
    for new_proj in extraction.get("new_projects", []):
        project = await resolve_project(
            session,
            name=new_proj.get("name", "Unnamed"),
            description=new_proj.get("description"),
        )
        resolved["projects"].append(project.slug)

    # Create tasks
    for task_data in extraction.get("tasks", []):
        title = (task_data.get("text") or "").strip()
        if not title:
            continue

        # Find project to link to
        project_id = None
        if resolved["projects"]:
            result = await session.execute(
                select(Project).where(Project.slug == resolved["projects"][0])
            )
            if proj := result.scalar_one_or_none():
                project_id = proj.id

        priority = task_data.get("priority", "normal")
        if priority not in ("urgent", "high", "normal", "low"):
            priority = "normal"

        task = Task(
            project_id=project_id,
            title=title,
            priority=priority,
            source_type="email",
            source_id=str(email.id),
            source_account_id=email.account_id,
        )
        if task_data.get("deadline"):
            try:
                task.due_date = datetime.fromisoformat(task_data["deadline"]).date()
            except (ValueError, TypeError):
                pass
        session.add(task)
        resolved["tasks_created"] += 1

    # Create commitments
    for commit_data in extraction.get("commitments", []):
        desc = (commit_data.get("text") or "").strip()
        if not desc:
            continue
        direction = "to_me" if commit_data.get("by") == "sender" else "from_me"
        commitment = Commitment(
            person_id=email.sender_id,
            direction=direction,
            description=desc,
            source_type="email",
            source_id=str(email.id),
        )
        if commit_data.get("deadline"):
            try:
                commitment.deadline = datetime.fromisoformat(commit_data["deadline"]).date()
            except (ValueError, TypeError):
                pass
        session.add(commitment)
        resolved["commitments_created"] += 1

    await session.flush()

    logger.info(
        "Resolved email %s: %d people, %d projects, %d tasks, %d commitments",
        email.gmail_id,
        len(resolved["people"]),
        len(resolved["projects"]),
        resolved["tasks_created"],
        resolved["commitments_created"],
    )
    return resolved
