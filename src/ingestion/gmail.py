"""Gmail ingestion via Google OAuth 2.0 and Gmail API."""

import base64
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from uuid import UUID

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.ingestion.accounts import get_oauth_token, store_oauth_token, update_sync_cursor
from src.storage.models import Email, EmailAccount, SyncState
from src.storage.raw import store_raw_interaction

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/drive.readonly",
]

CREDENTIALS_PATH = "~/.config/focus/google_credentials.json"


def _build_gmail_service(token_data: dict):
    """Build an authenticated Gmail API service."""
    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def run_oauth_flow(credentials_path: Optional[str] = None) -> dict:
    """Run the interactive OAuth flow and return token data."""
    from pathlib import Path

    creds_path = Path(credentials_path or CREDENTIALS_PATH).expanduser()
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def _parse_email_headers(headers: list[dict]) -> dict:
    """Extract useful headers from Gmail message headers."""
    result = {}
    header_map = {h["name"].lower(): h["value"] for h in headers}
    result["from"] = header_map.get("from", "")
    result["to"] = header_map.get("to", "")
    result["subject"] = header_map.get("subject", "")
    result["date"] = header_map.get("date", "")
    result["message_id"] = header_map.get("message-id", "")
    result["reply_to"] = header_map.get("reply-to", "")
    result["cc"] = header_map.get("cc", "")
    return result


def _extract_body(payload: dict) -> str:
    """Recursively extract the text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    if payload.get("mimeType", "").startswith("multipart/"):
        for part in payload.get("parts", []):
            body = _extract_body(part)
            if body:
                return body

    # Fallback: try HTML
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return ""


async def fetch_emails_full(
    session: AsyncSession,
    account: EmailAccount,
    max_results: int = 0,
) -> list[dict]:
    """Full sync — fetch all emails. Set max_results=0 for unlimited."""
    token_data = await get_oauth_token(session, account.id)
    if not token_data:
        raise ValueError(f"No OAuth token for account {account.name}")

    service = _build_gmail_service(token_data)
    messages = []
    page_token = None

    while max_results == 0 or len(messages) < max_results:
        batch_size = 100 if max_results == 0 else min(100, max_results - len(messages))
        result = service.users().messages().list(
            userId="me",
            maxResults=batch_size,
            pageToken=page_token,
        ).execute()

        msg_refs = result.get("messages", [])
        if not msg_refs:
            break

        for ref in msg_refs:
            msg = service.users().messages().get(
                userId="me",
                id=ref["id"],
                format="full",
            ).execute()
            messages.append(msg)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    logger.info("Fetched %d emails for account %s", len(messages), account.name)

    # Update sync cursor to latest historyId
    if messages:
        latest_history = max(int(m.get("historyId", 0)) for m in messages)
        await update_sync_cursor(session, account.id, str(latest_history))

    return messages


async def fetch_emails_incremental(
    session: AsyncSession,
    account: EmailAccount,
) -> list[dict]:
    """Incremental sync using historyId."""
    token_data = await get_oauth_token(session, account.id)
    if not token_data:
        raise ValueError(f"No OAuth token for account {account.name}")

    if not account.sync_cursor:
        logger.info("No sync cursor for %s, falling back to full sync", account.name)
        return await fetch_emails_full(session, account)

    service = _build_gmail_service(token_data)
    messages = []

    try:
        history = service.users().history().list(
            userId="me",
            startHistoryId=account.sync_cursor,
            historyTypes=["messageAdded"],
        ).execute()

        new_msg_ids = set()
        for record in history.get("history", []):
            for msg_added in record.get("messagesAdded", []):
                new_msg_ids.add(msg_added["message"]["id"])

        for msg_id in new_msg_ids:
            msg = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full",
            ).execute()
            messages.append(msg)

        # Update cursor
        new_history_id = history.get("historyId", account.sync_cursor)
        await update_sync_cursor(session, account.id, str(new_history_id))

    except Exception as e:
        if "404" in str(e) or "historyId" in str(e).lower():
            logger.warning("History expired for %s, doing full sync", account.name)
            return await fetch_emails_full(session, account)
        raise

    logger.info("Incremental sync found %d new emails for %s", len(messages), account.name)
    return messages


async def store_email(
    session: AsyncSession,
    account: EmailAccount,
    gmail_message: dict,
) -> Optional[Email]:
    """Process a raw Gmail message and store it in the database."""
    gmail_id = gmail_message["id"]
    thread_id = gmail_message.get("threadId")

    # Check for duplicate
    existing = await session.execute(
        select(Email).where(
            Email.account_id == account.id,
            Email.gmail_id == gmail_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    payload = gmail_message.get("payload", {})
    headers = _parse_email_headers(payload.get("headers", []))
    body = _extract_body(payload)
    snippet = gmail_message.get("snippet", "")
    labels = gmail_message.get("labelIds", [])

    # Parse date
    email_date = None
    if headers.get("date"):
        try:
            email_date = parsedate_to_datetime(headers["date"])
        except Exception:
            pass

    # Store raw interaction first
    raw_content = f"Subject: {headers.get('subject', '')}\nFrom: {headers.get('from', '')}\n\n{body}"
    await store_raw_interaction(
        session=session,
        source_type="email",
        raw_content=raw_content,
        source_id=gmail_id,
        account_id=account.id,
        raw_metadata=headers,
        interaction_date=email_date,
    )

    # Store processed email
    email = Email(
        account_id=account.id,
        gmail_id=gmail_id,
        thread_id=thread_id,
        subject=headers.get("subject"),
        snippet=snippet,
        full_body=body,
        labels=labels,
        email_date=email_date,
        raw_headers=headers,
    )
    session.add(email)
    await session.flush()
    return email


async def sync_account(
    session: AsyncSession,
    account: EmailAccount,
    full: bool = False,
) -> int:
    """Sync an email account. Returns count of new emails stored."""
    if full or not account.sync_cursor:
        raw_messages = await fetch_emails_full(session, account)
    else:
        raw_messages = await fetch_emails_incremental(session, account)

    stored = 0
    for msg in raw_messages:
        email = await store_email(session, account, msg)
        if email:
            stored += 1

    # Update sync state
    sync_key = f"gmail:{account.name}"
    sync_state = await session.get(SyncState, sync_key)
    if sync_state is None:
        sync_state = SyncState(
            id=sync_key,
            account_id=account.id,
            status="ok",
        )
        session.add(sync_state)
    sync_state.last_sync = datetime.now(timezone.utc)
    sync_state.cursor = account.sync_cursor
    sync_state.status = "ok"
    await session.flush()

    logger.info("Synced %s: %d new emails", account.name, stored)
    return stored
