"""iMessage ingestion — reads chat.db on macOS and stores messages."""

import logging
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Message, Person
from src.storage.raw import store_raw_interaction

logger = logging.getLogger(__name__)

# Apple's CoreData epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Default path to iMessage database
DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# Query to extract messages with chat info
MESSAGES_QUERY = """
SELECT
    m.ROWID,
    m.guid,
    m.text,
    m.is_from_me,
    m.date,
    m.handle_id,
    m.cache_has_attachments,
    h.id AS handle_id_str,
    c.chat_identifier,
    c.display_name AS chat_display_name
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
LEFT JOIN chat c ON cmj.chat_id = c.ROWID
WHERE m.text IS NOT NULL
  AND m.text != ''
  AND m.date > ?
ORDER BY m.date ASC
LIMIT ?
"""


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system() == "Darwin"


def apple_time_to_datetime(apple_timestamp: int) -> datetime:
    """Convert Apple CoreData timestamp to Python datetime.

    Apple timestamps are nanoseconds since 2001-01-01 00:00:00 UTC.
    """
    if apple_timestamp is None:
        return datetime.now(timezone.utc)
    # Timestamps after ~2017 are in nanoseconds
    if apple_timestamp >= 1_000_000_000_000:
        seconds = apple_timestamp / 1_000_000_000
    else:
        seconds = apple_timestamp
    return datetime.fromtimestamp(
        APPLE_EPOCH.timestamp() + seconds, tz=timezone.utc
    )


def datetime_to_apple_time(dt: datetime) -> int:
    """Convert Python datetime to Apple CoreData timestamp (nanoseconds)."""
    return int((dt.timestamp() - APPLE_EPOCH.timestamp()) * 1_000_000_000)


def read_messages(
    db_path: Path = DEFAULT_DB_PATH,
    since: Optional[datetime] = None,
    limit: int = 1000,
) -> list[dict]:
    """Read messages from the iMessage SQLite database.

    Returns a list of message dicts with normalized fields.
    """
    if not db_path.exists():
        logger.warning("iMessage database not found: %s", db_path)
        return []

    since_apple = datetime_to_apple_time(since) if since else 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(MESSAGES_QUERY, (since_apple, limit))
        messages = []
        for row in cursor:
            msg = {
                "rowid": row["ROWID"],
                "guid": row["guid"],
                "text": row["text"],
                "is_from_me": bool(row["is_from_me"]),
                "date": apple_time_to_datetime(row["date"]),
                "handle_id": row["handle_id_str"],
                "chat_id": row["chat_identifier"],
                "chat_name": row["chat_display_name"],
                "has_attachment": bool(row["cache_has_attachments"]),
            }
            messages.append(msg)
        return messages
    finally:
        conn.close()


async def resolve_message_sender(
    session: AsyncSession,
    handle_id: Optional[str],
) -> Optional[Person]:
    """Find a person by phone number or email (iMessage handle).

    Handles are typically phone numbers (+1234567890) or email addresses.
    """
    if not handle_id:
        return None

    # Try matching by phone
    result = await session.execute(
        select(Person).where(Person.phone == handle_id)
    )
    if person := result.scalar_one_or_none():
        return person

    # Try matching by email
    result = await session.execute(
        select(Person).where(Person.email == handle_id)
    )
    if person := result.scalar_one_or_none():
        return person

    return None


async def sync_imessages(
    session: AsyncSession,
    db_path: Path = DEFAULT_DB_PATH,
    since: Optional[datetime] = None,
    limit: int = 1000,
) -> dict:
    """Sync messages from iMessage database into Focus.

    Returns a summary dict with counts.
    """
    summary = {"messages_read": 0, "messages_stored": 0, "errors": 0}

    if not is_macos():
        logger.info("iMessage sync skipped — not macOS")
        return summary

    raw_messages = read_messages(db_path=db_path, since=since, limit=limit)
    summary["messages_read"] = len(raw_messages)

    for msg in raw_messages:
        try:
            # Check if already stored
            existing = await session.execute(
                select(Message).where(Message.source_id == msg["guid"])
            )
            if existing.scalar_one_or_none():
                continue

            # Resolve sender
            sender = None
            if not msg["is_from_me"] and msg["handle_id"]:
                sender = await resolve_message_sender(session, msg["handle_id"])

            # Store message
            message = Message(
                source_id=msg["guid"],
                sender_id=sender.id if sender else None,
                content=msg["text"],
                is_from_me=msg["is_from_me"],
                chat_id=msg["chat_id"],
                message_date=msg["date"],
                has_attachment=msg["has_attachment"],
            )
            session.add(message)

            # Store raw interaction
            await store_raw_interaction(
                session=session,
                source_type="imessage",
                raw_content=msg["text"],
                source_id=msg["guid"],
                raw_metadata={
                    "handle_id": msg["handle_id"],
                    "chat_id": msg["chat_id"],
                    "chat_name": msg["chat_name"],
                    "is_from_me": msg["is_from_me"],
                },
                interaction_date=msg["date"],
            )

            summary["messages_stored"] += 1

        except Exception as e:
            logger.error("Failed to store message %s: %s", msg["guid"], e)
            summary["errors"] += 1

    await session.flush()

    logger.info(
        "iMessage sync: %d read, %d stored, %d errors",
        summary["messages_read"],
        summary["messages_stored"],
        summary["errors"],
    )
    return summary
