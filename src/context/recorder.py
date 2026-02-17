"""Session recording — stores Claude Code conversations in the database."""

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.ingestion.claude_code import _parse_timestamp, parse_session_into_turns
from src.storage.db import get_session
from src.storage.jobs import enqueue_job
from src.storage.models import AgentSession, AgentTurn, AgentTurnContent

logger = logging.getLogger(__name__)


async def record_session(
    session: AsyncSession,
    session_id: str,
    transcript_path: str,
    workspace_path: str,
) -> dict:
    """Record a Claude Code session into the database.

    Parses the JSONL transcript into turns, upserts the session row,
    and inserts turns + content. Deduplicates turns by content_hash.

    Args:
        session: Database session.
        session_id: Claude Code session ID.
        transcript_path: Path to the .jsonl transcript file.
        workspace_path: Working directory of the session.

    Returns:
        Summary dict with turns_recorded, turns_skipped, session_id.
    """
    path = Path(transcript_path)
    if not path.exists():
        logger.warning("Transcript not found: %s", transcript_path)
        return {"session_id": session_id, "turns_recorded": 0, "turns_skipped": 0, "error": "file_not_found"}

    turns = parse_session_into_turns(path)
    if not turns:
        return {"session_id": session_id, "turns_recorded": 0, "turns_skipped": 0}

    # Get or create agent session
    result = await session.execute(
        select(AgentSession)
        .options(selectinload(AgentSession.turns))
        .where(AgentSession.session_id == session_id)
    )
    agent_session = result.scalar_one_or_none()

    if not agent_session:
        agent_session = AgentSession(
            session_id=session_id,
            transcript_path=transcript_path,
            workspace_path=workspace_path,
        )
        session.add(agent_session)
        await session.flush()
        existing_hashes = set()  # New session, no existing turns
    else:
        # Turns were eager-loaded via selectinload above
        existing_hashes = {t.content_hash for t in agent_session.turns}

    turns_recorded = 0
    turns_skipped = 0

    for turn_data in turns:
        if turn_data["content_hash"] in existing_hashes:
            turns_skipped += 1
            continue

        turn = AgentTurn(
            session_id=agent_session.id,
            turn_number=turn_data["turn_number"],
            user_message=turn_data.get("user_message"),
            content_hash=turn_data["content_hash"],
            model_name=turn_data.get("model_name"),
            tool_names=turn_data.get("tool_names"),
            started_at=_parse_timestamp(turn_data.get("started_at")),
            ended_at=_parse_timestamp(turn_data.get("ended_at")),
        )
        session.add(turn)
        await session.flush()

        content = AgentTurnContent(
            turn_id=turn.id,
            raw_jsonl=turn_data["raw_jsonl"],
            assistant_text=turn_data.get("assistant_text"),
            content_size=len(turn_data["raw_jsonl"]),
        )
        session.add(content)
        turns_recorded += 1

    # Update session metadata
    all_timestamps = [
        _parse_timestamp(t.get("started_at")) for t in turns
    ]
    valid_timestamps = [ts for ts in all_timestamps if ts is not None]

    if valid_timestamps:
        agent_session.started_at = agent_session.started_at or min(valid_timestamps)
        agent_session.last_activity_at = max(valid_timestamps)

    agent_session.turn_count = len(existing_hashes) + turns_recorded
    agent_session.transcript_path = transcript_path

    await session.flush()

    logger.info(
        "Recorded session %s: %d new turns, %d skipped",
        session_id[:12], turns_recorded, turns_skipped,
    )

    return {
        "session_id": session_id,
        "turns_recorded": turns_recorded,
        "turns_skipped": turns_skipped,
    }


async def enqueue_session_recording(
    session_id: str,
    transcript_path: str,
    workspace_path: str,
) -> bool:
    """Fast-path for the Stop hook: enqueue a recording job.

    Opens its own database session, enqueues the job, and returns
    immediately. Target: <200ms total.

    Args:
        session_id: Claude Code session ID.
        transcript_path: Path to the .jsonl transcript file.
        workspace_path: Working directory of the session.

    Returns:
        True if job was enqueued, False if duplicate.
    """
    try:
        # Use transcript file size in dedupe key so each new turn
        # creates a new job. The recorder deduplicates turns by
        # content_hash, so re-processing the same file is safe.
        file_size = 0
        try:
            file_size = Path(transcript_path).stat().st_size
        except OSError:
            pass

        async with get_session() as session:
            job = await enqueue_job(
                session=session,
                kind="session_process",
                payload={
                    "session_id": session_id,
                    "transcript_path": transcript_path,
                    "workspace_path": workspace_path,
                },
                dedupe_key=f"session_process:{session_id}:{file_size}",
                priority=5,
            )
            return job is not None
    except Exception as e:
        logger.error("Failed to enqueue recording: %s", e)
        return False
