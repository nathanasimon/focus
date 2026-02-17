"""Regex-based parsing for automated emails (receipts, shipping, etc.)."""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Email

logger = logging.getLogger(__name__)

# Regex patterns for common automated email data
PATTERNS = {
    "order_number": [
        re.compile(r"order\s*#?\s*(\d[\d-]{4,})", re.IGNORECASE),
        re.compile(r"order\s+number[:\s]*(\w[\w-]{4,})", re.IGNORECASE),
        re.compile(r"confirmation\s*#?\s*(\w[\w-]{4,})", re.IGNORECASE),
    ],
    "tracking_number": [
        # UPS: 1Z + 16 alphanumeric
        re.compile(r"\b(1Z[A-Z0-9]{16})\b"),
        # USPS: starts with 9, 22-27 digits
        re.compile(r"\b(9[0-9]{21,26})\b"),
        # FedEx: only match near tracking context to avoid false positives on random digit strings
        re.compile(r"(?:tracking|fedex|shipment)\s*(?:#|number|:)?\s*:?\s*(\d{12,15})\b", re.IGNORECASE),
        # Generic "tracking #" pattern
        re.compile(r"tracking\s*#?\s*:?\s*(\w{10,30})", re.IGNORECASE),
    ],
    "amount": [
        re.compile(r"\$\s*([\d,]+\.?\d{0,2})"),
        re.compile(r"total[:\s]*\$\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
        re.compile(r"amount[:\s]*\$\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
        re.compile(r"charged[:\s]*\$\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
    ],
    "date": [
        re.compile(r"(?:delivery|arrive|expected|estimated)\s+(?:by|on|date)[:\s]*(\w+ \d{1,2},?\s*\d{4})", re.IGNORECASE),
        re.compile(r"(?:ship|deliver)\w*\s+(?:on|by)\s+(\w+ \d{1,2},?\s*\d{4})", re.IGNORECASE),
        re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})"),
    ],
    "carrier": [
        re.compile(r"\b(UPS|USPS|FedEx|DHL|Amazon Logistics)\b", re.IGNORECASE),
    ],
    "status": [
        re.compile(r"\b(shipped|delivered|out for delivery|in transit|processing|confirmed|cancelled|refunded)\b", re.IGNORECASE),
    ],
}

# Sender-based categorization
AUTOMATED_CATEGORIES = {
    "order": ["order", "purchase", "receipt", "confirmation", "invoice"],
    "shipping": ["shipped", "tracking", "delivery", "package", "carrier"],
    "billing": ["bill", "payment", "statement", "due", "charged", "invoice"],
    "alert": ["alert", "notification", "warning", "security", "login"],
    "subscription": ["subscription", "renewal", "membership"],
}


def parse_automated_email(email: Email) -> dict:
    """Parse structured data from an automated email using regex patterns.

    Returns dict with:
        category, order_numbers, tracking_numbers, amounts, dates,
        carriers, statuses, raw_matches
    """
    text = f"{email.subject or ''}\n{email.full_body or email.snippet or ''}"

    result = {
        "category": _detect_category(email),
        "order_numbers": [],
        "tracking_numbers": [],
        "amounts": [],
        "dates": [],
        "carriers": [],
        "statuses": [],
        "raw_matches": {},
    }

    for field, patterns in PATTERNS.items():
        matches = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                matches.add(match.group(1) if match.lastindex else match.group(0))

        match_list = sorted(matches)
        result["raw_matches"][field] = match_list

        if field == "order_number":
            result["order_numbers"] = match_list
        elif field == "tracking_number":
            result["tracking_numbers"] = match_list
        elif field == "amount":
            result["amounts"] = [_clean_amount(a) for a in match_list]
        elif field == "date":
            result["dates"] = match_list
        elif field == "carrier":
            result["carriers"] = [c.title() for c in match_list]
        elif field == "status":
            result["statuses"] = [s.lower() for s in match_list]

    return result


def _detect_category(email: Email) -> str:
    """Detect the category of an automated email based on subject/sender."""
    text = f"{email.subject or ''} {(email.raw_headers or {}).get('from', '')}".lower()

    for category, keywords in AUTOMATED_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category

    return "other"


def _clean_amount(amount_str: str) -> float:
    """Clean and parse a dollar amount string."""
    try:
        cleaned = amount_str.replace(",", "")
        return float(cleaned)
    except ValueError:
        return 0.0


async def parse_and_update(
    session: AsyncSession,
    email: Email,
) -> dict:
    """Parse an automated email and update its database record."""
    result = parse_automated_email(email)

    email.extraction_result = result
    email.processed_at = datetime.now(timezone.utc)
    await session.flush()

    logger.info(
        "Parsed automated email %s: category=%s, %d orders, %d amounts",
        email.gmail_id,
        result["category"],
        len(result["order_numbers"]),
        len(result["amounts"]),
    )
    return result
