"""Ingestion pipeline — orchestrates syncing and processing for all accounts."""

import asyncio
import logging
from typing import Optional

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.ingestion.accounts import get_account_by_name, list_accounts
from src.ingestion.gmail import sync_account
from src.processing.classifier import classify_and_update
from src.processing.extractor import extract_and_update
from src.processing.regex_parser import parse_and_update
from src.processing.resolver import resolve_extraction
from src.storage.db import get_session
from src.storage.models import Email, EmailAccount

logger = logging.getLogger(__name__)

# Max concurrent API calls (Haiku classification + extraction)
MAX_CONCURRENCY = 10


async def run_full_sync(session: AsyncSession, account_name: Optional[str] = None) -> dict:
    """Run a full sync across all (or a specific) account(s).

    Returns a summary dict with counts.
    """
    settings = get_settings()
    summary = {
        "accounts": 0,
        "emails_fetched": 0,
        "drive_files_synced": 0,
        "classified": 0,
        "extracted": 0,
    }

    if account_name:
        account = await get_account_by_name(session, account_name)
        if not account:
            logger.error("Account not found: %s", account_name)
            return summary
        accounts = [account]
    else:
        accounts = await list_accounts(session, enabled_only=True)

    for account in accounts:
        summary["accounts"] += 1

        # Gmail sync
        try:
            count = await sync_account(session, account)
            summary["emails_fetched"] += count
            logger.info("Synced %s: %d new emails", account.name, count)
        except Exception as e:
            logger.error("Failed to sync Gmail for %s: %s", account.name, e)

        # Drive sync (shared OAuth)
        if settings.sync.drive_enabled:
            try:
                from src.ingestion.drive import sync_drive

                drive_summary = await sync_drive(session, account)
                summary["drive_files_synced"] += drive_summary["files_synced"]
                if drive_summary["files_synced"] > 0:
                    logger.info(
                        "Drive sync for %s: %d files",
                        account.name,
                        drive_summary["files_synced"],
                    )
            except Exception as e:
                logger.error("Failed to sync Drive for %s: %s", account.name, e)

    # iMessage sync
    if settings.sync.imessage_enabled:
        try:
            from src.ingestion.imessage import sync_imessages

            imsg_summary = await sync_imessages(session)
            summary["messages_synced"] = imsg_summary["messages_stored"]
        except Exception as e:
            logger.error("Failed to sync iMessages: %s", e)

    return summary


async def process_unprocessed_emails(session: AsyncSession, limit: int = 0) -> dict:
    """Process all unprocessed emails through the classification/extraction pipeline.

    Runs up to MAX_CONCURRENCY emails concurrently for speed.
    Each email gets its own DB session to avoid concurrent flush conflicts.
    Set limit=0 (default) for unlimited.
    Returns a summary dict.
    """
    summary = {"classified": 0, "deep_extracted": 0, "regex_parsed": 0, "skipped": 0, "errors": 0}

    query = (
        select(Email.id)
        .where(Email.classification.is_(None))
        .order_by(Email.email_date.desc().nullslast())
    )
    if limit > 0:
        query = query.limit(limit)
    result = await session.execute(query)
    email_ids = [row[0] for row in result.all()]

    if not email_ids:
        return summary

    # Commit so inner sessions (separate transactions) can see the emails
    await session.commit()

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _process_one(email_id: UUID) -> dict:
        """Process a single email through classify → extract → resolve."""
        local = {"classified": 0, "deep_extracted": 0, "regex_parsed": 0, "skipped": 0, "errors": 0}
        async with semaphore:
            async with get_session() as inner_session:
                try:
                    email = await inner_session.get(Email, email_id)
                    if not email:
                        local["errors"] += 1
                        return local

                    # Stage 1: Classify
                    classification = await classify_and_update(inner_session, email)
                    local["classified"] += 1

                    route = classification.get("route_to", "skip")
                    still_relevant = classification.get("still_relevant", True)

                    # Stage 2: Route to appropriate handler
                    if route == "deep_analysis" and still_relevant:
                        extraction = await extract_and_update(inner_session, email)
                        local["deep_extracted"] += 1

                        # Stage 3: Entity resolution
                        if extraction.get("tasks") or extraction.get("commitments") or extraction.get("people_mentioned") or extraction.get("project_links"):
                            await resolve_extraction(inner_session, email, extraction)

                    elif route == "deep_analysis" and not still_relevant:
                        # Human but stale — record the classification but skip extraction
                        local["skipped"] += 1

                    elif route == "regex_parse":
                        await parse_and_update(inner_session, email)
                        local["regex_parsed"] += 1

                    else:
                        local["skipped"] += 1

                    # Stage 4: Index for semantic search
                    _try_index_email(email)

                except Exception as e:
                    logger.error("Failed to process email %s: %s", email_id, e)
                    local["errors"] += 1

        return local

    results = await asyncio.gather(*[_process_one(eid) for eid in email_ids])

    for r in results:
        for k in summary:
            summary[k] += r[k]

    return summary


def _try_index_email(email: Email) -> None:
    """Index an email for semantic search. Silently skips if chromadb unavailable."""
    try:
        from src.storage.vectors import get_vector_store

        text = f"{email.subject or ''}\n{email.full_body or email.snippet or ''}".strip()
        if not text:
            return
        meta = {"classification": email.classification or "unknown", "needs_reply": email.needs_reply}
        if email.email_date:
            meta["date"] = email.email_date.isoformat()
        get_vector_store().add_email(str(email.id), text, meta)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Vector indexing skipped for email %s: %s", email.gmail_id, e)


async def sync_and_process(
    session: AsyncSession,
    account_name: Optional[str] = None,
    process_limit: int = 0,
) -> dict:
    """Full pipeline: sync new emails, then process unprocessed ones."""
    sync_summary = await run_full_sync(session, account_name)
    process_summary = await process_unprocessed_emails(session, limit=process_limit)
    return {**sync_summary, **process_summary}
