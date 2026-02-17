"""Google Drive ingestion via Changes API with shared OAuth credentials."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.accounts import get_oauth_token
from src.storage.models import Document, EmailAccount, SyncState
from src.storage.raw import store_raw_interaction

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]

# Google Workspace MIME types → export format for text extraction.
# None means skip (no useful text to extract).
EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": None,
    "application/vnd.google-apps.form": None,
    "application/vnd.google-apps.site": None,
    "application/vnd.google-apps.map": None,
    "application/vnd.google-apps.shortcut": None,
    "application/vnd.google-apps.folder": None,
}

# Non-Google MIME types we can download and extract text from.
TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")

# Max file size to download for text extraction (5 MB).
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


def _build_drive_service(token_data: dict):
    """Build an authenticated Google Drive API service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    # Use scopes from the stored token (set during OAuth), not a hardcoded subset
    creds = Credentials.from_authorized_user_info(token_data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


def _is_google_workspace_type(mime_type: str) -> bool:
    """Check if a MIME type is a Google Workspace document."""
    return mime_type.startswith("application/vnd.google-apps.")


def _should_extract_text(mime_type: str) -> bool:
    """Determine if we should attempt text extraction for this MIME type."""
    if _is_google_workspace_type(mime_type):
        return EXPORT_MIME_MAP.get(mime_type) is not None
    return mime_type.startswith(TEXT_MIME_PREFIXES)


def _export_google_doc(service, file_id: str, mime_type: str) -> str:
    """Export a Google Workspace document as plain text.

    Args:
        service: Google Drive API service.
        file_id: The Drive file ID.
        mime_type: The Google Workspace MIME type.

    Returns:
        Exported text content, or empty string on failure.
    """
    export_mime = EXPORT_MIME_MAP.get(mime_type)
    if not export_mime:
        return ""

    try:
        response = service.files().export(
            fileId=file_id,
            mimeType=export_mime,
        ).execute()
        if isinstance(response, bytes):
            return response.decode("utf-8", errors="replace")
        return str(response)
    except Exception as e:
        logger.warning("Failed to export Google Doc %s: %s", file_id, e)
        return ""


def _download_file_text(service, file_id: str, size: int) -> str:
    """Download a non-Google file and return its text content.

    Only downloads files under MAX_DOWNLOAD_BYTES to avoid memory issues.
    """
    if size > MAX_DOWNLOAD_BYTES:
        logger.debug("Skipping large file %s (%d bytes)", file_id, size)
        return ""

    try:
        response = service.files().get_media(fileId=file_id).execute()
        if isinstance(response, bytes):
            return response.decode("utf-8", errors="replace")
        return str(response)
    except Exception as e:
        logger.warning("Failed to download file %s: %s", file_id, e)
        return ""


def _build_folder_path(service, parents: list[str], cache: dict) -> str:
    """Resolve the folder path from parent IDs.

    Uses a cache to avoid redundant API calls for the same folder.
    Returns a path like "My Drive/Projects/Docs".
    """
    if not parents:
        return ""

    parent_id = parents[0]  # Drive files have at most one parent
    parts = []
    current = parent_id

    # Walk up the tree, caching as we go
    while current:
        if current in cache:
            parts.append(cache[current])
            break

        try:
            folder = service.files().get(
                fileId=current,
                fields="id,name,parents",
            ).execute()
            name = folder.get("name", "")
            cache[current] = name
            parts.append(name)
            folder_parents = folder.get("parents", [])
            current = folder_parents[0] if folder_parents else None
        except Exception:
            # Root or inaccessible — stop
            break

    parts.reverse()
    return "/".join(parts)


def _content_hash(text: str) -> str:
    """Compute SHA-256 hash of text content for dedup."""
    return hashlib.sha256(text.encode()).hexdigest()


# Fields we request from the Drive API for each file.
FILE_FIELDS = "id,name,mimeType,modifiedTime,size,parents,trashed,owners"
FILES_LIST_FIELDS = f"nextPageToken,files({FILE_FIELDS})"
CHANGES_LIST_FIELDS = f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS}))"


async def fetch_files_full(
    session: AsyncSession,
    account: EmailAccount,
    max_results: int = 1000,
) -> list[dict]:
    """Full sync — list all files in Drive for initial onboarding.

    Returns list of raw file metadata dicts from the Drive API.
    """
    token_data = await get_oauth_token(session, account.id)
    if not token_data:
        raise ValueError(f"No OAuth token for account {account.name}")

    service = _build_drive_service(token_data)
    files = []
    page_token = None

    while len(files) < max_results:
        page_size = min(100, max_results - len(files))
        result = service.files().list(
            pageSize=page_size,
            pageToken=page_token,
            fields=FILES_LIST_FIELDS,
            q="trashed = false",
            orderBy="modifiedTime desc",
        ).execute()

        batch = result.get("files", [])
        if not batch:
            break
        files.extend(batch)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    logger.info("Full Drive sync: fetched %d files for account %s", len(files), account.name)

    # Get a start page token for future incremental syncs
    start_token = service.changes().getStartPageToken().execute()
    sync_key = f"drive:{account.name}"
    sync_state = await session.get(SyncState, sync_key)
    if sync_state is None:
        sync_state = SyncState(id=sync_key, account_id=account.id)
        session.add(sync_state)
    sync_state.cursor = start_token.get("startPageToken")
    sync_state.last_sync = datetime.now(timezone.utc)
    sync_state.status = "ok"
    await session.flush()

    return files


async def fetch_files_incremental(
    session: AsyncSession,
    account: EmailAccount,
) -> tuple[list[dict], list[str]]:
    """Incremental sync using the Changes API.

    Returns:
        (changed_files, removed_file_ids) — files that changed and IDs that were removed.
    """
    token_data = await get_oauth_token(session, account.id)
    if not token_data:
        raise ValueError(f"No OAuth token for account {account.name}")

    sync_key = f"drive:{account.name}"
    sync_state = await session.get(SyncState, sync_key)

    if not sync_state or not sync_state.cursor:
        logger.info("No Drive sync cursor for %s, falling back to full sync", account.name)
        files = await fetch_files_full(session, account, max_results=500)
        return files, []

    service = _build_drive_service(token_data)
    changed_files = []
    removed_ids = []
    page_token = sync_state.cursor

    while page_token:
        result = service.changes().list(
            pageToken=page_token,
            spaces="drive",
            includeRemoved=True,
            fields=CHANGES_LIST_FIELDS,
            pageSize=100,
        ).execute()

        for change in result.get("changes", []):
            if change.get("removed"):
                removed_ids.append(change["fileId"])
            elif change.get("file"):
                file_data = change["file"]
                if not file_data.get("trashed"):
                    changed_files.append(file_data)

        # newStartPageToken means we've consumed all changes
        if "newStartPageToken" in result:
            page_token = None
            sync_state.cursor = result["newStartPageToken"]
        else:
            page_token = result.get("nextPageToken")

    sync_state.last_sync = datetime.now(timezone.utc)
    sync_state.status = "ok"
    await session.flush()

    logger.info(
        "Incremental Drive sync for %s: %d changed, %d removed",
        account.name, len(changed_files), len(removed_ids),
    )
    return changed_files, removed_ids


async def store_document(
    session: AsyncSession,
    account: EmailAccount,
    file_data: dict,
    service,
    folder_cache: dict,
) -> Optional[Document]:
    """Process a Drive file and store/update it in the database.

    Returns the Document if created/updated, None if skipped (no change or unsupported).
    """
    drive_id = file_data["id"]
    mime_type = file_data.get("mimeType", "")
    title = file_data.get("name", "")

    # Skip folders and unsupported Workspace types
    if mime_type == "application/vnd.google-apps.folder":
        return None

    # Extract text content
    text_content = ""
    if _should_extract_text(mime_type):
        if _is_google_workspace_type(mime_type):
            text_content = _export_google_doc(service, drive_id, mime_type)
        else:
            file_size = int(file_data.get("size", 0))
            text_content = _download_file_text(service, drive_id, file_size)

    # Compute content hash for dedup
    new_hash = _content_hash(text_content) if text_content else None

    # Build folder path
    parents = file_data.get("parents", [])
    folder_path = _build_folder_path(service, parents, folder_cache) if parents else ""

    # Parse modification time
    last_modified = None
    if file_data.get("modifiedTime"):
        try:
            last_modified = datetime.fromisoformat(
                file_data["modifiedTime"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # Check for existing document
    existing = await session.execute(
        select(Document).where(Document.drive_id == drive_id)
    )
    doc = existing.scalar_one_or_none()

    if doc:
        # Content hasn't changed — skip
        if new_hash and doc.content_hash == new_hash:
            return None

        # Update existing document
        doc.title = title
        doc.mime_type = mime_type
        doc.folder_path = folder_path
        doc.last_modified = last_modified
        if text_content:
            doc.extracted_text = text_content
            doc.content_hash = new_hash
    else:
        # Create new document
        doc = Document(
            drive_id=drive_id,
            title=title,
            mime_type=mime_type,
            folder_path=folder_path,
            last_modified=last_modified,
            content_hash=new_hash,
            extracted_text=text_content or None,
        )
        session.add(doc)

    await session.flush()

    # Store raw interaction for permanent archive
    if text_content:
        raw_content = f"Title: {title}\nPath: {folder_path}\nType: {mime_type}\n\n{text_content}"
        await store_raw_interaction(
            session=session,
            source_type="drive",
            raw_content=raw_content,
            source_id=drive_id,
            account_id=account.id,
            raw_metadata={
                "title": title,
                "mime_type": mime_type,
                "folder_path": folder_path,
                "modified_time": file_data.get("modifiedTime"),
            },
            interaction_date=last_modified,
        )

    logger.debug("Stored document: %s (%s)", title, drive_id)
    return doc


async def remove_documents(
    session: AsyncSession,
    removed_ids: list[str],
) -> int:
    """Mark removed Drive files in the database.

    We don't delete them — we clear the extracted_text to save space
    but keep the metadata for audit trail.
    Returns count of documents updated.
    """
    count = 0
    for drive_id in removed_ids:
        result = await session.execute(
            select(Document).where(Document.drive_id == drive_id)
        )
        doc = result.scalar_one_or_none()
        if doc:
            doc.extracted_text = None
            doc.content_hash = None
            count += 1

    if count:
        await session.flush()
        logger.info("Marked %d documents as removed", count)
    return count


async def sync_drive(
    session: AsyncSession,
    account: EmailAccount,
    full: bool = False,
) -> dict:
    """Sync Google Drive for an account. Returns summary dict.

    Args:
        session: Database session.
        account: The email account (shared OAuth).
        full: Force full sync even if we have a cursor.
    """
    summary = {"files_synced": 0, "files_removed": 0, "files_skipped": 0, "errors": 0}

    token_data = await get_oauth_token(session, account.id)
    if not token_data:
        logger.warning("No OAuth token for account %s, skipping Drive sync", account.name)
        return summary

    try:
        service = _build_drive_service(token_data)
    except Exception as e:
        logger.error("Failed to build Drive service for %s: %s", account.name, e)
        summary["errors"] += 1
        return summary

    folder_cache: dict[str, str] = {}
    removed_ids: list[str] = []

    if full:
        file_list = await fetch_files_full(session, account)
    else:
        file_list, removed_ids = await fetch_files_incremental(session, account)

    # Process changed files
    for file_data in file_list:
        try:
            doc = await store_document(session, account, file_data, service, folder_cache)
            if doc:
                summary["files_synced"] += 1
            else:
                summary["files_skipped"] += 1
        except Exception as e:
            logger.error("Failed to process Drive file %s: %s", file_data.get("id"), e)
            summary["errors"] += 1

    # Handle removals
    if removed_ids:
        summary["files_removed"] = await remove_documents(session, removed_ids)

    logger.info(
        "Drive sync for %s: %d synced, %d removed, %d skipped, %d errors",
        account.name,
        summary["files_synced"],
        summary["files_removed"],
        summary["files_skipped"],
        summary["errors"],
    )
    return summary
