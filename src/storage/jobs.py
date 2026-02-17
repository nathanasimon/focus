"""Durable job queue backed by PostgreSQL with lease-based locking."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import FocusJob

logger = logging.getLogger(__name__)


async def enqueue_job(
    session: AsyncSession,
    kind: str,
    payload: dict,
    dedupe_key: Optional[str] = None,
    priority: int = 10,
    max_attempts: int = 10,
) -> Optional[FocusJob]:
    """Enqueue a job, deduplicating by dedupe_key if provided.

    Args:
        session: Database session.
        kind: Job type (e.g., 'session_process', 'turn_summary').
        payload: JSON-serializable job data.
        dedupe_key: If set, prevents duplicate jobs with same key.
        priority: Lower number = higher priority.
        max_attempts: Max retries before permanent failure.

    Returns:
        The created job, or None if a duplicate exists.
    """
    job_id = uuid.uuid4()

    if dedupe_key:
        stmt = pg_insert(FocusJob).values(
            id=job_id,
            kind=kind,
            payload=payload,
            dedupe_key=dedupe_key,
            priority=priority,
            max_attempts=max_attempts,
            status="queued",
        ).on_conflict_do_nothing(index_elements=["dedupe_key"])

        result = await session.execute(stmt)
        if result.rowcount == 0:
            logger.debug("Job deduplicated: %s", dedupe_key)
            return None

        await session.flush()
        return await session.get(FocusJob, job_id)
    else:
        job = FocusJob(
            id=job_id,
            kind=kind,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
        )
        session.add(job)
        await session.flush()
        return job


async def claim_job(
    session: AsyncSession,
    kinds: Optional[list[str]] = None,
    lease_seconds: int = 300,
) -> Optional[FocusJob]:
    """Claim the next available job using lease-based locking.

    Uses FOR UPDATE SKIP LOCKED to avoid contention between workers.

    Args:
        session: Database session.
        kinds: Filter to specific job kinds. None means all kinds.
        lease_seconds: How long the lease lasts before expiry.

    Returns:
        The claimed job, or None if no jobs available.
    """
    kind_filter = ""
    params: dict = {"lease_seconds": lease_seconds}

    if kinds:
        kind_filter = "AND kind = ANY(:kinds)"
        params["kinds"] = kinds

    query = text(f"""
        UPDATE focus_jobs
        SET status = 'processing',
            locked_until = now() + make_interval(secs => :lease_seconds),
            attempts = attempts + 1,
            updated_at = now()
        WHERE id = (
            SELECT id FROM focus_jobs
            WHERE status IN ('queued', 'retry')
              AND (locked_until IS NULL OR locked_until < now())
              {kind_filter}
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id
    """)

    result = await session.execute(query, params)
    row = result.fetchone()
    if not row:
        return None

    await session.flush()
    job = await session.get(FocusJob, row[0])
    return job


async def complete_job(
    session: AsyncSession,
    job_id: uuid.UUID,
) -> None:
    """Mark a job as done.

    Args:
        session: Database session.
        job_id: The job to complete.
    """
    await session.execute(
        update(FocusJob)
        .where(FocusJob.id == job_id)
        .values(status="done", updated_at=datetime.now(timezone.utc))
    )


async def fail_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    error_message: str,
) -> None:
    """Mark a job as failed or set to retry with exponential backoff.

    If attempts < max_attempts: status='retry' with exponential backoff.
    Otherwise: status='failed' permanently.

    Args:
        session: Database session.
        job_id: The job that failed.
        error_message: Description of the failure.
    """
    job = await session.get(FocusJob, job_id)
    if not job:
        logger.warning("Cannot fail job %s: not found", job_id)
        return

    now = datetime.now(timezone.utc)

    if job.attempts < job.max_attempts:
        backoff_seconds = min((2 ** job.attempts) * 30, 3600)
        await session.execute(
            update(FocusJob)
            .where(FocusJob.id == job_id)
            .values(
                status="retry",
                error_message=error_message,
                locked_until=now + timedelta(seconds=backoff_seconds),
                updated_at=now,
            )
        )
        logger.info(
            "Job %s retry #%d in %ds: %s",
            job_id, job.attempts, backoff_seconds, error_message,
        )
    else:
        await session.execute(
            update(FocusJob)
            .where(FocusJob.id == job_id)
            .values(
                status="failed",
                error_message=error_message,
                updated_at=now,
            )
        )
        logger.warning("Job %s permanently failed after %d attempts: %s", job_id, job.attempts, error_message)


async def expire_stale_leases(
    session: AsyncSession,
) -> int:
    """Reset jobs whose lease has expired back to 'retry'.

    Args:
        session: Database session.

    Returns:
        Number of expired leases reset.
    """
    result = await session.execute(
        update(FocusJob)
        .where(
            FocusJob.status == "processing",
            FocusJob.locked_until < datetime.now(timezone.utc),
        )
        .values(
            status="retry",
            locked_until=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    count = result.rowcount
    if count > 0:
        logger.info("Expired %d stale job leases", count)
    return count


async def get_job_stats(
    session: AsyncSession,
) -> dict[str, int]:
    """Return job counts grouped by status.

    Args:
        session: Database session.

    Returns:
        Dict mapping status to count.
    """
    result = await session.execute(
        text("SELECT status, count(*) FROM focus_jobs GROUP BY status")
    )
    return {row[0]: row[1] for row in result.all()}
