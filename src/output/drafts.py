"""Email draft queue — suggested replies for humans to review."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Email, EmailAccount

logger = logging.getLogger(__name__)


async def generate_drafts(
    session: AsyncSession,
    vault_path: Path,
) -> None:
    """Generate EMAIL-DRAFTS.md with suggested replies."""
    result = await session.execute(
        select(Email, EmailAccount)
        .outerjoin(EmailAccount, Email.account_id == EmailAccount.id)
        .where(
            Email.needs_reply.is_(True),
            Email.reply_sent.is_(False),
            Email.reply_suggested.isnot(None),
        )
        .order_by(Email.urgency.asc(), Email.email_date.asc())
    )
    rows = result.all()

    lines = ["# Suggested Emails", ""]

    # Split by urgency
    urgent = [(e, a) for e, a in rows if e.urgency == "urgent"]
    normal = [(e, a) for e, a in rows if e.urgency != "urgent"]

    if urgent:
        lines.append("## High Priority")
        lines.append("")
        for email, account in urgent:
            _format_draft(lines, email, account)

    if normal:
        lines.append("## Normal Priority")
        lines.append("")
        for email, account in normal:
            _format_draft(lines, email, account)

    if not rows:
        lines.append("_No suggested replies at this time._")

    inbox_dir = vault_path / "Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    (inbox_dir / "EMAIL-DRAFTS.md").write_text("\n".join(lines) + "\n")
    logger.info("Generated EMAIL-DRAFTS.md with %d drafts", len(rows))


def _format_draft(lines: list[str], email: Email, account: EmailAccount | None) -> None:
    """Format a single email draft entry."""
    sender = (email.raw_headers or {}).get("from", "unknown")
    name = sender.split("<")[0].strip().strip('"')
    subject = email.subject or "(no subject)"
    account_label = f"[{account.name}] " if account else ""

    days_waiting = ""
    if email.email_date:
        delta = (datetime.now(timezone.utc) - email.email_date).days
        if delta > 0:
            days_waiting = f" ({delta} days ago)"

    lines.append(f"### {account_label}Reply to: {name} — {subject}{days_waiting}")

    # Why this needs a reply
    extraction = email.extraction_result or {}
    if extraction.get("waiting_on"):
        for w in extraction["waiting_on"]:
            lines.append(f"**Why**: Waiting on {w.get('text', 'something')}")
    elif extraction.get("questions"):
        unanswered = [q for q in extraction["questions"] if not q.get("answered")]
        if unanswered:
            lines.append(f"**Why**: {len(unanswered)} unanswered question(s)")

    lines.append("")
    lines.append(f"> {email.reply_suggested}")
    lines.append("")
    lines.append("---")
    lines.append("")
