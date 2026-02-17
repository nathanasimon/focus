"""Email classification using Claude Haiku."""

import json
import logging
import re
import time
from datetime import date

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.storage.models import Email
from src.storage.raw import store_ai_conversation

logger = logging.getLogger(__name__)

# Sender patterns that are never human — skip the API call entirely
_NOREPLY_RE = re.compile(
    r"(^|<)(no[-_]?reply|noreply|mailer[-_]?daemon|notifications?|updates?|info@|support@|news@|marketing@|digest@)",
    re.IGNORECASE,
)

# Known bulk-mail platforms (From domain or via header)
_BULK_DOMAINS = {
    "mailchimp.com", "sendgrid.net", "constantcontact.com", "mailgun.org",
    "amazonses.com", "postmarkapp.com", "hubspot.com", "klaviyo.com",
    "brevo.com", "mailjet.com", "campaign-archive.com",
}


def pre_classify(email: Email) -> dict | None:
    """Try to classify an email using zero-cost heuristics (no API call).

    Returns a classification dict if confident, or None to fall through to the LLM.
    """
    sender = (email.raw_headers or {}).get("from", "")
    headers = email.raw_headers or {}
    body = (email.full_body or email.snippet or "").lower()

    # Check for noreply-style sender
    if _NOREPLY_RE.search(sender):
        return {
            "classification": "automated",
            "confidence": 0.95,
            "urgency": "low",
            "sender_type": "company",
            "route_to": "regex_parse",
        }

    # Check for List-Unsubscribe header (mailing lists / newsletters)
    if headers.get("list-unsubscribe") or headers.get("List-Unsubscribe"):
        return {
            "classification": "newsletter",
            "confidence": 0.90,
            "urgency": "low",
            "sender_type": "company",
            "route_to": "archive",
        }

    # Check for precedence: bulk/list
    precedence = (headers.get("precedence") or headers.get("Precedence") or "").lower()
    if precedence in ("bulk", "list", "junk"):
        return {
            "classification": "newsletter",
            "confidence": 0.90,
            "urgency": "low",
            "sender_type": "company",
            "route_to": "archive",
        }

    # Check sender domain against known bulk platforms
    domain_match = re.search(r"@([\w.-]+)>?\s*$", sender)
    if domain_match:
        domain = domain_match.group(1).lower()
        for bulk in _BULK_DOMAINS:
            if domain == bulk or domain.endswith("." + bulk):
                return {
                    "classification": "newsletter",
                    "confidence": 0.85,
                    "urgency": "low",
                    "sender_type": "company",
                    "route_to": "archive",
                }

    # Check for unsubscribe near end of body (strong newsletter signal)
    if len(body) > 200:
        tail = body[-500:]
        if "unsubscribe" in tail and ("preferences" in tail or "opt out" in tail or "opt-out" in tail or "manage" in tail):
            return {
                "classification": "newsletter",
                "confidence": 0.80,
                "urgency": "low",
                "sender_type": "company",
                "route_to": "archive",
            }

    return None

CLASSIFICATION_PROMPT = """Classify this email into exactly one category. Respond with JSON only, no other text.

Categories (pick the FIRST match):
- spam: Cold outreach, sales pitches, recruiter emails, SEO offers, link building requests, unsolicited intros, scams, "Hey I noticed your company..." emails. When in doubt between spam and human, pick spam.
- newsletter: Marketing emails, subscriptions, promotional content, digest emails, product announcements, mailing lists
- system: Password resets, 2FA codes, account notifications, security alerts, login confirmations
- automated: Receipts, shipping confirmations, order updates, calendar invites, payment confirmations, app notifications
- human: A REAL conversation from someone the recipient likely knows personally or works with. Must show genuine personal context — references to shared projects, prior conversations, or specific asks. NOT cold outreach disguised as personal.

Also assess:
- urgency: urgent / normal / low
- sender_type: known (colleague, friend, family) / unknown (never interacted) / company (business entity)

Email:
From: {sender}
Date: {date}
Subject: {subject}
Body (first 500 chars): {body}

Today's date: {today}

Respond ONLY with this JSON format:
{{"classification": "spam", "confidence": 0.94, "urgency": "low", "sender_type": "unknown", "route_to": "skip", "still_relevant": false}}

Rules for route_to:
- human → "deep_analysis"
- automated → "regex_parse"
- newsletter → "archive"
- spam → "skip"
- system → "skip"

still_relevant: Is this email still actionable TODAY? An email from 3 months ago asking "are you free Friday?" is NOT still relevant. A recent email about an ongoing project IS. Old automated emails (receipts, confirmations) are never relevant. Default to false if the email is more than 2 weeks old UNLESS it references an ongoing commitment or project.
"""


async def classify_email(
    session: AsyncSession,
    email: Email,
) -> dict:
    """Classify an email using Claude Haiku via the Anthropic API.

    Returns classification dict with keys:
        classification, confidence, urgency, sender_type, route_to
    """
    settings = get_settings()
    sender = (email.raw_headers or {}).get("from", "unknown")
    subject = email.subject or ""
    body = (email.full_body or "")[:500]
    email_date = email.email_date.strftime("%Y-%m-%d") if email.email_date else "unknown"
    today = date.today().isoformat()

    prompt = CLASSIFICATION_PROMPT.format(
        sender=sender,
        subject=subject,
        body=body,
        date=email_date,
        today=today,
    )

    request_payload = {
        "model": settings.anthropic.model,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_payload,
            )
            response.raise_for_status()
            result = response.json()

        latency_ms = int((time.time() - start_time) * 1000)
        raw_response = result.get("content", [{}])[0].get("text", "")
        input_tokens = result.get("usage", {}).get("input_tokens", 0)
        output_tokens = result.get("usage", {}).get("output_tokens", 0)

        # Parse JSON from response
        classification = _parse_classification(raw_response)

        # Log AI conversation
        if settings.raw_storage.store_ai_conversations:
            await store_ai_conversation(
                session=session,
                session_type="classification",
                model=settings.anthropic.model,
                prompt_version="v1.0",
                request_messages=[{"role": "user", "content": prompt}],
                response_content={"raw": raw_response, "parsed": classification},
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )

        return classification

    except Exception as e:
        logger.error("Classification failed for email %s: %s", email.gmail_id, e)
        return _default_classification()


def _parse_classification(raw_response: str) -> dict:
    """Parse the JSON classification from the LLM response."""
    try:
        text = raw_response.strip()
        if not text:
            logger.warning("Empty classification response from LLM")
            return _default_classification()

        # Find the first { and last }
        start = text.index("{")
        end = text.rindex("}") + 1
        json_str = text[start:end]
        result = json.loads(json_str)

        # Validate required fields
        valid_classifications = {"human", "automated", "newsletter", "spam", "system"}
        if result.get("classification") not in valid_classifications:
            result["classification"] = "newsletter"
            result["confidence"] = 0.0

        valid_urgency = {"urgent", "normal", "low"}
        if result.get("urgency") not in valid_urgency:
            result["urgency"] = "normal"

        valid_sender = {"known", "unknown", "company"}
        if result.get("sender_type") not in valid_sender:
            result["sender_type"] = "unknown"

        route_map = {
            "human": "deep_analysis",
            "automated": "regex_parse",
            "newsletter": "archive",
            "spam": "skip",
            "system": "skip",
        }
        result["route_to"] = route_map.get(result["classification"], "deep_analysis")

        return result

    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse classification JSON: %s", raw_response[:200])
        return _default_classification()


def _default_classification() -> dict:
    """Return a safe default classification when parsing fails.

    Defaults to newsletter/archive — not human — so failures don't
    waste deep-analysis API calls on junk.
    """
    return {
        "classification": "newsletter",
        "confidence": 0.0,
        "urgency": "low",
        "sender_type": "unknown",
        "route_to": "archive",
    }


async def classify_and_update(
    session: AsyncSession,
    email: Email,
) -> dict:
    """Classify an email and update its database record.

    Tries zero-cost heuristics first; only calls the LLM if uncertain.
    """
    result = pre_classify(email)
    if result is None:
        result = await classify_email(session, email)

    email.classification = result["classification"]
    email.urgency = result.get("urgency", "normal")
    await session.flush()

    logger.info(
        "Classified email %s as %s (confidence: %.2f)",
        email.gmail_id,
        result["classification"],
        result.get("confidence", 0),
    )
    return result
