"""Multi-account email management for Focus."""

import json
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import EmailAccount

logger = logging.getLogger(__name__)

# Token storage directory
TOKEN_DIR = Path.home() / ".config/focus/tokens"


def _ensure_token_dir():
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)


async def add_account(
    session: AsyncSession,
    name: str,
    email: str,
    provider: str = "gmail",
    priority_weight: float = 1.0,
    process_newsletters: bool = False,
) -> EmailAccount:
    """Add a new email account."""
    account = EmailAccount(
        name=name,
        email=email,
        provider=provider,
        priority_weight=priority_weight,
        process_newsletters=process_newsletters,
    )
    session.add(account)
    await session.flush()
    logger.info("Added account: %s (%s)", name, email)
    return account


async def get_account_by_name(session: AsyncSession, name: str) -> Optional[EmailAccount]:
    """Look up an account by its friendly name."""
    result = await session.execute(
        select(EmailAccount).where(EmailAccount.name == name)
    )
    return result.scalar_one_or_none()


async def get_account_by_email(session: AsyncSession, email: str) -> Optional[EmailAccount]:
    """Look up an account by email address."""
    result = await session.execute(
        select(EmailAccount).where(EmailAccount.email == email)
    )
    return result.scalar_one_or_none()


async def get_account(session: AsyncSession, account_id: UUID) -> Optional[EmailAccount]:
    """Get an account by ID."""
    return await session.get(EmailAccount, account_id)


async def list_accounts(session: AsyncSession, enabled_only: bool = False) -> list[EmailAccount]:
    """List all configured email accounts."""
    query = select(EmailAccount).order_by(EmailAccount.name)
    if enabled_only:
        query = query.where(EmailAccount.sync_enabled.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


async def update_account_priority(
    session: AsyncSession,
    account_id: UUID,
    priority_weight: float,
) -> None:
    """Update an account's priority weight."""
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(priority_weight=priority_weight)
    )


async def disable_account(session: AsyncSession, account_id: UUID) -> None:
    """Disable syncing for an account."""
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(sync_enabled=False)
    )


async def enable_account(session: AsyncSession, account_id: UUID) -> None:
    """Enable syncing for an account."""
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(sync_enabled=True)
    )


async def store_oauth_token(
    session: AsyncSession,
    account_id: UUID,
    token_data: dict,
) -> None:
    """Store OAuth token data for an account."""
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(oauth_token=token_data)
    )
    # Also persist to disk as backup
    _ensure_token_dir()
    account = await session.get(EmailAccount, account_id)
    if account:
        token_path = TOKEN_DIR / f"{account.name}.json"
        token_path.write_text(json.dumps(token_data))


async def get_oauth_token(session: AsyncSession, account_id: UUID) -> Optional[dict]:
    """Retrieve OAuth token data for an account."""
    account = await session.get(EmailAccount, account_id)
    if account and account.oauth_token:
        return account.oauth_token

    # Try disk fallback
    if account:
        token_path = TOKEN_DIR / f"{account.name}.json"
        if token_path.exists():
            return json.loads(token_path.read_text())

    return None


async def update_sync_cursor(
    session: AsyncSession,
    account_id: UUID,
    cursor: str,
) -> None:
    """Update the sync cursor (historyId) for an account."""
    from datetime import datetime, timezone

    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(sync_cursor=cursor, last_sync=datetime.now(timezone.utc))
    )
