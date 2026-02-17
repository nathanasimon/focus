"""FastAPI REST API for Focus."""

import logging
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.storage.db import get_session

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Focus API",
    description="REST API for Focus — your AI-powered second brain",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic response models ---

class ProjectResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    tier: str
    status: str
    description: Optional[str] = None
    user_pinned: bool = False
    user_priority: Optional[str] = None
    user_deadline: Optional[date] = None
    mention_count: int = 0

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str
    project_id: Optional[UUID] = None
    due_date: Optional[date] = None
    user_pinned: bool = False
    user_priority: Optional[str] = None

    model_config = {"from_attributes": True}


class PersonResponse(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    relationship_type: Optional[str] = None
    organization: Optional[str] = None

    model_config = {"from_attributes": True}


class EmailResponse(BaseModel):
    id: UUID
    subject: Optional[str] = None
    classification: Optional[str] = None
    urgency: Optional[str] = None
    needs_reply: bool = False
    email_date: Optional[datetime] = None
    sender_name: Optional[str] = None
    reply_suggested: Optional[str] = None

    model_config = {"from_attributes": True}


class CommitmentResponse(BaseModel):
    id: UUID
    person_name: Optional[str] = None
    direction: str
    description: str
    deadline: Optional[date] = None
    status: str
    source_type: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SprintResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    project_name: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    is_active: bool

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: UUID
    drive_id: str
    title: Optional[str] = None
    mime_type: Optional[str] = None
    folder_path: Optional[str] = None
    last_modified: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SyncRequest(BaseModel):
    account_name: Optional[str] = None
    process: bool = True


class SyncResponse(BaseModel):
    accounts: int
    emails_fetched: int
    drive_files_synced: int = 0
    classified: int = 0
    deep_extracted: int = 0
    regex_parsed: int = 0


class PriorityItem(BaseModel):
    name: str
    slug: str
    score: float
    pinned: bool
    priority: Optional[str] = None
    deadline: Optional[date] = None


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
):
    """List all projects, optionally filtered."""
    from sqlalchemy import select
    from src.storage.models import Project

    async with get_session() as session:
        query = select(Project).order_by(Project.last_activity.desc().nullslast())
        if status:
            query = query.where(Project.status == status)
        if tier:
            query = query.where(Project.tier == tier)
        result = await session.execute(query)
        return result.scalars().all()


@app.get("/projects/{slug}", response_model=ProjectResponse)
async def get_project(slug: str):
    """Get a single project by slug."""
    from sqlalchemy import select
    from src.storage.models import Project

    async with get_session() as session:
        result = await session.execute(select(Project).where(Project.slug == slug))
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project


@app.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    project_slug: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List tasks, optionally filtered."""
    from sqlalchemy import select
    from src.storage.models import Project, Task

    async with get_session() as session:
        query = select(Task).order_by(Task.created_at.desc())

        if project_slug:
            result = await session.execute(select(Project.id).where(Project.slug == project_slug))
            proj_id = result.scalar_one_or_none()
            if proj_id:
                query = query.where(Task.project_id == proj_id)

        if status:
            query = query.where(Task.status == status)

        result = await session.execute(query.limit(limit))
        return result.scalars().all()


@app.get("/people", response_model=list[PersonResponse])
async def list_people(limit: int = Query(50, le=200)):
    """List known people."""
    from sqlalchemy import select
    from src.storage.models import Person

    async with get_session() as session:
        result = await session.execute(
            select(Person).order_by(Person.last_contact.desc().nullslast()).limit(limit)
        )
        return result.scalars().all()


@app.get("/emails", response_model=list[EmailResponse])
async def list_emails(
    classification: Optional[str] = Query(None),
    needs_reply: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
):
    """List processed emails."""
    from sqlalchemy import select
    from src.storage.models import Email

    async with get_session() as session:
        query = select(Email).order_by(Email.email_date.desc().nullslast())
        if classification:
            query = query.where(Email.classification == classification)
        if needs_reply is not None:
            query = query.where(Email.needs_reply == needs_reply)
        result = await session.execute(query.limit(limit))
        return result.scalars().all()


@app.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    folder: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List synced Drive documents."""
    from sqlalchemy import select
    from src.storage.models import Document

    async with get_session() as session:
        query = select(Document).order_by(Document.last_modified.desc().nullslast())
        if folder:
            query = query.where(Document.folder_path.ilike(f"%{folder}%"))
        result = await session.execute(query.limit(limit))
        return result.scalars().all()


@app.get("/priorities", response_model=list[PriorityItem])
async def get_priorities(
    scope: str = Query("all", description="all, today, or week"),
):
    """Get projects ranked by effective priority."""
    from src.priority import get_priority_ranking

    async with get_session() as session:
        ranked = await get_priority_ranking(session, scope=scope)
        return [
            PriorityItem(
                name=r["name"],
                slug=r["slug"],
                score=r["score"],
                pinned=r["pinned"],
                priority=r["priority"],
                deadline=r["deadline"],
            )
            for r in ranked
        ]


@app.post("/sync", response_model=SyncResponse)
async def trigger_sync(request: SyncRequest):
    """Trigger a sync manually via API."""
    from src.ingestion.pipeline import process_unprocessed_emails, run_full_sync

    async with get_session() as session:
        sync_result = await run_full_sync(session, request.account_name)
        proc_result = {"classified": 0, "deep_extracted": 0, "regex_parsed": 0}

        if request.process:
            proc_result = await process_unprocessed_emails(session)

        return SyncResponse(
            accounts=sync_result["accounts"],
            emails_fetched=sync_result["emails_fetched"],
            drive_files_synced=sync_result.get("drive_files_synced", 0),
            **proc_result,
        )


@app.post("/generate")
async def trigger_generate(project_slug: Optional[str] = Query(None)):
    """Trigger vault and CLAUDE.md regeneration."""
    from src.output.claude_md import generate_claude_md
    from src.output.vault import generate_vault

    async with get_session() as session:
        await generate_vault(session)
        await generate_claude_md(session, project_slug=project_slug)

    return {"status": "generated"}


class SearchResult(BaseModel):
    collection: str
    id: str
    text: str
    metadata: dict = {}
    score: float = 0.0


@app.get("/search", response_model=list[SearchResult])
async def semantic_search_endpoint(
    q: str = Query(..., description="Search query"),
    collections: Optional[str] = Query(None, description="Comma-separated collection names"),
    limit: int = Query(10, le=50),
):
    """Semantic search across all indexed data."""
    try:
        from src.storage.vectors import semantic_search

        col_list = collections.split(",") if collections else None
        results = await semantic_search(q, collections=col_list, n_results=limit)
        return [
            SearchResult(
                collection=r["collection"],
                id=r["id"],
                text=(r.get("text") or "")[:500],
                metadata=r.get("metadata", {}),
                score=round(1 - r.get("distance", 1.0), 4),
            )
            for r in results
        ]
    except ImportError:
        raise HTTPException(status_code=501, detail="chromadb not installed")


@app.get("/emails/needs-reply", response_model=list[EmailResponse])
async def list_needs_reply(limit: int = Query(50, le=200)):
    """List emails needing a reply, with sender info."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from src.storage.models import Email

    async with get_session() as session:
        result = await session.execute(
            select(Email)
            .options(selectinload(Email.sender))
            .where(Email.needs_reply.is_(True), Email.reply_sent.is_(False))
            .order_by(Email.email_date.asc().nullslast())
            .limit(limit)
        )
        emails = result.scalars().all()
        return [
            EmailResponse(
                id=e.id,
                subject=e.subject,
                classification=e.classification,
                urgency=e.urgency,
                needs_reply=e.needs_reply,
                email_date=e.email_date,
                sender_name=e.sender.name if e.sender else None,
                reply_suggested=e.reply_suggested,
            )
            for e in emails
        ]


@app.get("/commitments", response_model=list[CommitmentResponse])
async def list_commitments(
    status: Optional[str] = Query("open"),
    direction: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List commitments, optionally filtered by status and direction."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from src.storage.models import Commitment

    async with get_session() as session:
        query = (
            select(Commitment)
            .options(selectinload(Commitment.person))
            .order_by(Commitment.created_at.desc())
        )
        if status:
            query = query.where(Commitment.status == status)
        if direction:
            query = query.where(Commitment.direction == direction)
        result = await session.execute(query.limit(limit))
        commitments = result.scalars().all()
        return [
            CommitmentResponse(
                id=c.id,
                person_name=c.person.name if c.person else None,
                direction=c.direction,
                description=c.description,
                deadline=c.deadline,
                status=c.status,
                source_type=c.source_type,
                created_at=c.created_at,
            )
            for c in commitments
        ]


@app.get("/sprints", response_model=list[SprintResponse])
async def list_sprints(active_only: bool = Query(True)):
    """List sprints, optionally only active ones."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from src.storage.models import Sprint

    async with get_session() as session:
        query = select(Sprint).options(selectinload(Sprint.project))
        if active_only:
            query = query.where(Sprint.is_active.is_(True))
        query = query.order_by(Sprint.ends_at.asc())
        result = await session.execute(query)
        sprints = result.scalars().all()
        return [
            SprintResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                project_name=s.project.name if s.project else None,
                starts_at=s.starts_at,
                ends_at=s.ends_at,
                is_active=s.is_active,
            )
            for s in sprints
        ]


@app.post("/capture")
async def trigger_capture(
    project_dir: Optional[str] = Query(None),
    extract: bool = Query(True),
):
    """Capture decisions from Claude Code sessions."""
    from src.ingestion.claude_code import scan_sessions

    async with get_session() as session:
        summary = await scan_sessions(session, project_dir=project_dir, extract=extract)
    return summary
