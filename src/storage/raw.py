"""Raw interaction archive — permanent storage for all ingested data."""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import AIConversation, RawInteraction

logger = logging.getLogger(__name__)


async def store_raw_interaction(
    session: AsyncSession,
    source_type: str,
    raw_content: str,
    source_id: Optional[str] = None,
    account_id: Optional[UUID] = None,
    raw_metadata: Optional[dict] = None,
    interaction_date: Optional[datetime] = None,
) -> RawInteraction:
    """Store a raw interaction, deduplicating by content hash."""
    content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

    # Check for duplicate
    existing = await session.execute(
        select(RawInteraction).where(RawInteraction.content_hash == content_hash)
    )
    if found := existing.scalar_one_or_none():
        logger.debug("Duplicate raw interaction skipped: %s", content_hash[:12])
        return found

    interaction = RawInteraction(
        source_type=source_type,
        source_id=source_id,
        account_id=account_id,
        raw_content=raw_content,
        raw_metadata=raw_metadata or {},
        content_hash=content_hash,
        interaction_date=interaction_date,
    )
    session.add(interaction)
    await session.flush()
    logger.debug("Stored raw interaction: %s/%s", source_type, source_id)
    return interaction


async def store_ai_conversation(
    session: AsyncSession,
    session_type: str,
    model: str,
    request_messages: list[dict],
    response_content: dict,
    prompt_version: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
    latency_ms: Optional[int] = None,
    source_interaction_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
) -> AIConversation:
    """Log an AI API call for permanent record."""
    conv = AIConversation(
        session_type=session_type,
        model=model,
        prompt_version=prompt_version,
        request_messages=request_messages,
        response_content=response_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        source_interaction_id=source_interaction_id,
        project_id=project_id,
    )
    session.add(conv)
    await session.flush()
    return conv


async def get_unprocessed_interactions(
    session: AsyncSession,
    source_type: Optional[str] = None,
    since: Optional[datetime] = None,
    extraction_version: Optional[str] = None,
    limit: int = 100,
) -> list[RawInteraction]:
    """Fetch raw interactions that need (re-)processing."""
    query = select(RawInteraction)

    if source_type:
        query = query.where(RawInteraction.source_type == source_type)
    if since:
        query = query.where(RawInteraction.interaction_date >= since)
    if extraction_version:
        # Get items NOT processed with this version (or never processed)
        query = query.where(
            (RawInteraction.extraction_version != extraction_version)
            | (RawInteraction.extraction_version.is_(None))
        )

    query = query.order_by(RawInteraction.interaction_date.asc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def mark_processed(
    session: AsyncSession,
    interaction_id: UUID,
    extraction_version: str,
    extraction_model: str,
    extraction_result: dict,
) -> None:
    """Mark a raw interaction as processed with extraction results."""
    interaction = await session.get(RawInteraction, interaction_id)
    if interaction:
        interaction.extraction_version = extraction_version
        interaction.extraction_model = extraction_model
        interaction.extraction_result = extraction_result
        interaction.last_processed_at = datetime.now(timezone.utc)
        await session.flush()
