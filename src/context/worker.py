"""Background worker for processing context system jobs."""

import asyncio
import logging
import re
import signal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.db import get_session
from src.storage.jobs import claim_job, complete_job, expire_stale_leases, fail_job
from src.storage.models import (
    AgentSession,
    AgentTurn,
    AgentTurnEntity,
    FocusJob,
    Person,
    Project,
)

logger = logging.getLogger(__name__)

_running = True

JOB_KINDS = [
    "session_process",
    "turn_summary",
    "entity_extract",
    "artifact_extract",
    "session_summary",
    "skill_extract",
]


def _handle_shutdown(signum, frame):
    """Signal handler for graceful shutdown."""
    global _running
    _running = False
    logger.info("Worker shutdown signal received")


async def process_session_job(job: FocusJob) -> None:
    """Process a session_process job: parse and store conversation turns.

    Args:
        job: The job to process.
    """
    from src.context.recorder import record_session
    from src.storage.jobs import enqueue_job

    payload = job.payload
    session_id = payload["session_id"]
    transcript_path = payload["transcript_path"]
    workspace_path = payload.get("workspace_path", "")

    async with get_session() as session:
        result = await record_session(
            session=session,
            session_id=session_id,
            transcript_path=transcript_path,
            workspace_path=workspace_path,
        )

        if result.get("error"):
            raise RuntimeError(f"Recording failed: {result['error']}")

        # Auto-link to project by workspace path
        if workspace_path:
            await _link_session_to_project(session, session_id, workspace_path)

        # Enqueue child jobs for newly recorded turns
        if result["turns_recorded"] > 0:
            agent_session = (await session.execute(
                select(AgentSession).where(AgentSession.session_id == session_id)
            )).scalar_one_or_none()

            if agent_session:
                turns = (await session.execute(
                    select(AgentTurn)
                    .where(AgentTurn.session_id == agent_session.id)
                    .where(AgentTurn.assistant_summary.is_(None))
                )).scalars().all()

                for turn in turns:
                    await enqueue_job(
                        session=session,
                        kind="turn_summary",
                        payload={"turn_id": str(turn.id)},
                        dedupe_key=f"turn_summary:{turn.id}",
                        priority=15,
                    )
                    await enqueue_job(
                        session=session,
                        kind="entity_extract",
                        payload={"turn_id": str(turn.id)},
                        dedupe_key=f"entity_extract:{turn.id}",
                        priority=20,
                    )
                    await enqueue_job(
                        session=session,
                        kind="artifact_extract",
                        payload={"turn_id": str(turn.id)},
                        dedupe_key=f"artifact_extract:{turn.id}",
                        priority=18,
                    )

                # Session summary job (lower priority, runs after turns)
                await enqueue_job(
                    session=session,
                    kind="session_summary",
                    payload={"session_id": session_id},
                    dedupe_key=f"session_summary:{session_id}",
                    priority=25,
                )

    logger.info(
        "Session job done: %s (%d recorded, %d skipped)",
        session_id[:12], result["turns_recorded"], result["turns_skipped"],
    )


async def _link_session_to_project(
    session: AsyncSession,
    session_id: str,
    workspace_path: str,
) -> None:
    """Auto-link a session to a Focus project by matching workspace path.

    Tries to match the last path component to a project slug.

    Args:
        session: Database session.
        session_id: Claude Code session ID.
        workspace_path: Working directory path.
    """
    from pathlib import Path

    dir_name = Path(workspace_path).name.lower()
    if not dir_name:
        return

    # Check explicit project selection first
    from src.context.project_state import get_active_project

    explicit_slug = get_active_project(workspace=workspace_path)
    search_slug = explicit_slug or dir_name

    result = await session.execute(
        select(Project).where(Project.slug == search_slug, Project.status == "active")
    )
    project = result.scalar_one_or_none()

    if project:
        agent_session = (await session.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )).scalar_one_or_none()

        if agent_session and not agent_session.project_id:
            agent_session.project_id = project.id
            logger.info("Linked session %s to project %s", session_id[:12], project.slug)


async def process_turn_summary_job(job: FocusJob) -> None:
    """Generate LLM summary for a single conversation turn.

    Args:
        job: The job to process. Payload must contain turn_id.
    """
    import uuid

    turn_id = uuid.UUID(job.payload["turn_id"])

    async with get_session() as session:
        turn = await session.get(AgentTurn, turn_id)
        if not turn:
            logger.warning("Turn %s not found, skipping summary", turn_id)
            return

        if turn.assistant_summary:
            return

        # Build summary from user message (no LLM call if message is short)
        user_msg = (turn.user_message or "")[:200]
        if len(user_msg) < 50:
            turn.turn_title = user_msg[:80] if user_msg else "Short exchange"
            turn.assistant_summary = user_msg
            await session.flush()
            return

        # Try LLM summarization, fall back to truncation
        try:
            title, summary = await _llm_summarize_turn(user_msg)
            turn.turn_title = title
            turn.assistant_summary = summary
        except Exception as e:
            logger.debug("LLM summary failed, using truncation: %s", e)
            turn.turn_title = user_msg[:80]
            turn.assistant_summary = user_msg[:200]

        await session.flush()


async def _llm_summarize_turn(user_message: str) -> tuple[str, str]:
    """Call LLM to generate turn title and summary.

    Args:
        user_message: The user's message text.

    Returns:
        Tuple of (title, summary).

    Raises:
        Exception: If LLM call fails.
    """
    from src.config import get_settings

    settings = get_settings()

    if not settings.anthropic.api_key:
        raise RuntimeError("No Anthropic API key")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic.api_key)
    response = client.messages.create(
        model=settings.context.turn_summary_model,
        max_tokens=200,
        system="Generate a short title (5-10 words) and a 1-sentence summary of what the user asked/discussed. Return as: TITLE: <title>\nSUMMARY: <summary>",
        messages=[{"role": "user", "content": user_message[:1000]}],
    )

    text = response.content[0].text
    title = ""
    summary = ""

    for line in text.strip().split("\n"):
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.startswith("SUMMARY:"):
            summary = line[8:].strip()

    return title or user_message[:80], summary or user_message[:200]


async def process_entity_extract_job(job: FocusJob) -> None:
    """Extract entity mentions from a turn using keyword matching.

    Scans user_message and assistant_text against known projects and people.

    Args:
        job: The job to process. Payload must contain turn_id.
    """
    import uuid

    from sqlalchemy.orm import selectinload

    turn_id = uuid.UUID(job.payload["turn_id"])

    async with get_session() as session:
        turn = await session.get(
            AgentTurn,
            turn_id,
            options=[selectinload(AgentTurn.content)],
        )
        if not turn:
            return

        # Build searchable text
        text_parts = []
        if turn.user_message:
            text_parts.append(turn.user_message)
        if turn.content and turn.content.assistant_text:
            text_parts.append(turn.content.assistant_text)
        full_text = "\n".join(text_parts).lower()

        if not full_text:
            return

        # Load known entities
        projects = (await session.execute(
            select(Project).where(Project.status == "active")
        )).scalars().all()

        people = (await session.execute(
            select(Person)
        )).scalars().all()

        # Match projects
        for project in projects:
            pattern = re.compile(r'\b' + re.escape(project.slug) + r'\b', re.IGNORECASE)
            if pattern.search(full_text):
                entity = AgentTurnEntity(
                    turn_id=turn_id,
                    entity_type="project",
                    entity_id=project.id,
                    entity_name=project.name,
                    confidence=0.9,
                )
                session.add(entity)
            elif project.name and re.search(
                r'\b' + re.escape(project.name.lower()) + r'\b', full_text
            ):
                entity = AgentTurnEntity(
                    turn_id=turn_id,
                    entity_type="project",
                    entity_id=project.id,
                    entity_name=project.name,
                    confidence=0.7,
                )
                session.add(entity)

        # Match people
        for person in people:
            if person.name and len(person.name) > 2:
                if re.search(r'\b' + re.escape(person.name.lower()) + r'\b', full_text):
                    entity = AgentTurnEntity(
                        turn_id=turn_id,
                        entity_type="person",
                        entity_id=person.id,
                        entity_name=person.name,
                        confidence=0.8,
                    )
                    session.add(entity)

        await session.flush()


async def process_artifact_extract_job(job: FocusJob) -> None:
    """Extract artifacts (files, commands, errors) from a turn's raw JSONL.

    Args:
        job: The job to process. Payload must contain turn_id.
    """
    import uuid

    from sqlalchemy.orm import selectinload

    from src.context.artifact_extractor import extract_artifacts
    from src.storage.models import AgentTurnArtifact

    turn_id = uuid.UUID(job.payload["turn_id"])

    async with get_session() as session:
        turn = await session.get(
            AgentTurn,
            turn_id,
            options=[selectinload(AgentTurn.content)],
        )
        if not turn or not turn.content:
            return

        raw_jsonl = turn.content.raw_jsonl
        if not raw_jsonl:
            return

        artifacts = extract_artifacts(raw_jsonl)

        # Store individual artifacts
        for artifact in artifacts.artifacts:
            session.add(AgentTurnArtifact(
                turn_id=turn_id,
                artifact_type=artifact.artifact_type,
                artifact_value=artifact.artifact_value,
                artifact_metadata=artifact.artifact_metadata,
            ))

        # Update summary columns on content
        if artifacts.files_touched:
            turn.content.files_touched = artifacts.files_touched
        if artifacts.commands_run:
            turn.content.commands_run = artifacts.commands_run
        if artifacts.errors_encountered:
            turn.content.errors_encountered = artifacts.errors_encountered
        turn.content.tool_call_count = artifacts.tool_call_count

        await session.flush()
        logger.info(
            "Artifacts extracted for turn %s: %d artifacts, %d files, %d commands, %d errors",
            turn_id, len(artifacts.artifacts), len(artifacts.files_touched),
            len(artifacts.commands_run), len(artifacts.errors_encountered),
        )


async def process_session_summary_job(job: FocusJob) -> None:
    """Generate aggregate session summary from turn summaries.

    Args:
        job: The job to process. Payload must contain session_id.
    """
    cc_session_id = job.payload["session_id"]

    async with get_session() as session:
        agent_session = (await session.execute(
            select(AgentSession)
            .options(
                __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(AgentSession.turns)
            )
            .where(AgentSession.session_id == cc_session_id)
        )).scalar_one_or_none()

        if not agent_session:
            return

        # Build summary from turn titles/summaries
        parts = []
        for turn in sorted(agent_session.turns, key=lambda t: t.turn_number):
            if turn.turn_title:
                parts.append(turn.turn_title)
            elif turn.user_message:
                parts.append(turn.user_message[:80])

        if not parts:
            return

        # Simple concatenation for session title/summary
        agent_session.session_title = parts[0][:100] if parts else None
        agent_session.session_summary = "; ".join(parts)[:500]
        agent_session.is_processed = True

        await session.flush()
        logger.info("Session summary generated: %s", cc_session_id[:12])

        # Enqueue skill extraction (low priority, runs after everything else)
        await enqueue_job(
            session=session,
            kind="skill_extract",
            payload={"session_id": cc_session_id},
            dedupe_key=f"skill_extract:{cc_session_id}",
            priority=30,
        )


async def process_skill_extract_job(job: FocusJob) -> None:
    """Analyze a completed session and auto-generate a skill if it qualifies.

    Args:
        job: The job to process. Payload must contain session_id.
    """
    from src.skills.analyzer import analyze_session_for_skill
    from src.skills.generator import generate_skill_md
    from src.skills.installer import install_skill as install_skill_to_disk

    cc_session_id = job.payload["session_id"]

    async with get_session() as session:
        agent_session = (await session.execute(
            select(AgentSession)
            .where(AgentSession.session_id == cc_session_id)
        )).scalar_one_or_none()

        if not agent_session:
            return

        candidate = await analyze_session_for_skill(session, agent_session)
        if not candidate:
            logger.debug("Session %s did not qualify for skill", cc_session_id[:12])
            return

        skill = await generate_skill_md(
            description=candidate.description,
            context=candidate.context,
            source="auto",
        )
        if not skill:
            logger.debug("Skill generation failed for session %s", cc_session_id[:12])
            return

        try:
            path = install_skill_to_disk(name=skill.name, content=skill.full_content)
            logger.info(
                "Auto-generated skill '%s' from session %s -> %s",
                skill.name, cc_session_id[:12], path,
            )

            # Record in database for dedup tracking
            import hashlib

            from src.storage.models import GeneratedSkillRecord

            record = GeneratedSkillRecord(
                name=skill.name,
                description=skill.description,
                source="auto",
                source_session_id=cc_session_id,
                installed_path=str(path),
                scope="personal",
                quality_score=candidate.quality_score,
                skill_content_hash=hashlib.md5(
                    " ".join(skill.description.lower().split()).encode()
                ).hexdigest(),
            )
            session.add(record)
            await session.flush()

        except (FileExistsError, ValueError) as e:
            logger.debug("Skipped skill for session %s: %s", cc_session_id[:12], e)


async def _dispatch_job(job: FocusJob) -> None:
    """Dispatch a job to the appropriate handler.

    Args:
        job: The job to dispatch.

    Raises:
        ValueError: If job kind is unknown.
    """
    handlers = {
        "session_process": process_session_job,
        "turn_summary": process_turn_summary_job,
        "entity_extract": process_entity_extract_job,
        "artifact_extract": process_artifact_extract_job,
        "session_summary": process_session_summary_job,
        "skill_extract": process_skill_extract_job,
    }

    handler = handlers.get(job.kind)
    if not handler:
        raise ValueError(f"Unknown job kind: {job.kind}")

    await handler(job)


async def process_pending_jobs(max_jobs: int = 20) -> int:
    """Process up to max_jobs pending jobs.

    For embedding in the daemon cycle or one-shot processing.

    Args:
        max_jobs: Maximum number of jobs to process.

    Returns:
        Number of jobs processed successfully.
    """
    processed = 0

    async with get_session() as session:
        await expire_stale_leases(session)

    for _ in range(max_jobs):
        async with get_session() as session:
            job = await claim_job(session, kinds=JOB_KINDS)
            if not job:
                break

            try:
                await _dispatch_job(job)
                await complete_job(session, job.id)
                processed += 1
            except Exception as e:
                logger.error("Job %s (%s) failed: %s", job.id, job.kind, e)
                await fail_job(session, job.id, str(e))

    return processed


async def run_worker(poll_interval: float = 2.0) -> None:
    """Main worker loop — claims and processes jobs continuously.

    Args:
        poll_interval: Seconds to sleep when no jobs are available.
    """
    global _running
    _running = True

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    logger.info("Context worker started (poll interval: %.1fs)", poll_interval)

    consecutive_empty = 0

    while _running:
        try:
            # Expire stale leases periodically
            async with get_session() as session:
                await expire_stale_leases(session)

            # Try to claim and process a job
            async with get_session() as session:
                job = await claim_job(session, kinds=JOB_KINDS)
                if not job:
                    consecutive_empty += 1
                    if consecutive_empty % 30 == 0:
                        logger.debug("No jobs for %d cycles", consecutive_empty)
                    await asyncio.sleep(poll_interval)
                    continue

                consecutive_empty = 0
                try:
                    await _dispatch_job(job)
                    await complete_job(session, job.id)
                    logger.info("Completed job %s (%s)", job.id, job.kind)
                except Exception as e:
                    logger.error("Job %s (%s) failed: %s", job.id, job.kind, e)
                    await fail_job(session, job.id, str(e))

        except Exception as e:
            logger.error("Worker error: %s", e, exc_info=True)
            await asyncio.sleep(poll_interval)

    logger.info("Context worker stopped")
