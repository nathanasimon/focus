"""Deep extraction using Claude Haiku for human emails."""

import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.storage.models import Email, Project
from src.storage.raw import store_ai_conversation

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "v1.0"

EXTRACTION_SYSTEM = """You are an AI assistant that extracts structured data from emails.
Given an email and context about known projects and people, extract actionable information.

Return ONLY valid JSON with these fields:
- tasks: [{text, assigned_to ("me" or name), deadline (ISO date or null), priority ("urgent"/"high"/"normal"/"low")}]
- commitments: [{text, by ("sender" or "me"), deadline (ISO date or null)}]
- questions: [{text, answered (bool)}]
- waiting_on: [{text, from (name), since (ISO date or null)}]
- project_links: [project-slug strings matching known projects]
- new_projects: [{name, description}] (only if clearly a new distinct project)
- people_mentioned: [name strings]
- sentiment: "positive" / "neutral" / "negative" / "urgent"
- reply_needed: bool
- reply_urgency: "urgent" / "normal" / "low" / "none"
- suggested_reply: string or null (brief, matching casual professional tone)

IMPORTANT: Consider the email date vs today's date. If the email is more than 2 weeks old:
- reply_needed should almost always be false (the moment has passed)
- suggested_reply should be null
- tasks with deadlines in the past should have priority "low"
- Still extract people_mentioned and project_links (useful for building the graph)

Be conservative — only extract what's clearly stated. Don't infer tasks that aren't there."""


def _build_extraction_prompt(email: Email, known_projects: list[str], known_people: list[str]) -> str:
    """Build the extraction prompt with email content and context."""
    sender = (email.raw_headers or {}).get("from", "unknown")
    subject = email.subject or "(no subject)"
    body = email.full_body or email.snippet or ""

    context_parts = []
    if known_projects:
        context_parts.append(f"Known projects: {', '.join(known_projects)}")
    if known_people:
        context_parts.append(f"Known people: {', '.join(known_people)}")

    context = "\n".join(context_parts) if context_parts else "No known context yet."

    today = date.today().isoformat()

    return f"""Context:
{context}

Today's date: {today}

Email:
From: {sender}
Subject: {subject}
Date: {email.email_date or 'unknown'}

Body:
{body[:3000]}

Extract structured data from this email as JSON."""


async def extract_email(
    session: AsyncSession,
    email: Email,
    known_projects: Optional[list[str]] = None,
    known_people: Optional[list[str]] = None,
) -> dict:
    """Extract structured data from a human email using Claude Haiku.

    Returns extraction dict with tasks, commitments, questions, etc.
    """
    settings = get_settings()

    if not settings.anthropic.api_key:
        logger.warning("No Anthropic API key configured, skipping extraction")
        return _empty_extraction()

    if known_projects is None:
        result = await session.execute(
            select(Project.slug).where(Project.status == "active")
        )
        known_projects = [row[0] for row in result.all()]

    if known_people is None:
        from src.storage.models import Person

        result = await session.execute(select(Person.name).limit(100))
        known_people = [row[0] for row in result.all()]

    user_prompt = _build_extraction_prompt(email, known_projects, known_people)

    messages = [{"role": "user", "content": user_prompt}]

    start_time = time.time()

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic.api_key)
        response = client.messages.create(
            model=settings.anthropic.model,
            max_tokens=2000,
            system=EXTRACTION_SYSTEM,
            messages=messages,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_text = response.content[0].text
        extraction = _parse_extraction(raw_text)

        # Track costs
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

        # Log AI conversation
        if settings.raw_storage.store_ai_conversations:
            await store_ai_conversation(
                session=session,
                session_type="extraction",
                model=settings.anthropic.model,
                prompt_version=EXTRACTION_PROMPT_VERSION,
                request_messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    *messages,
                ],
                response_content={"raw": raw_text, "parsed": extraction},
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )

        logger.info(
            "Extracted from email %s: %d tasks, %d commitments (cost: $%.4f)",
            email.gmail_id,
            len(extraction.get("tasks", [])),
            len(extraction.get("commitments", [])),
            cost_usd,
        )
        return extraction

    except Exception as e:
        logger.error("Extraction failed for email %s: %s", email.gmail_id, e)
        return _empty_extraction()


def _parse_extraction(raw_text: str) -> dict:
    """Parse the JSON extraction from Claude's response."""
    try:
        text = raw_text.strip()
        # Strip markdown code fences robustly
        if text.startswith("```"):
            # Remove opening fence (```json, ```, etc.)
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()
            text = text[:-3]

        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse extraction JSON: %s", raw_text[:300])
        return _empty_extraction()


def _empty_extraction() -> dict:
    """Return an empty extraction result."""
    return {
        "tasks": [],
        "commitments": [],
        "questions": [],
        "waiting_on": [],
        "project_links": [],
        "new_projects": [],
        "people_mentioned": [],
        "sentiment": "neutral",
        "reply_needed": False,
        "reply_urgency": "none",
        "suggested_reply": None,
    }


async def extract_and_update(
    session: AsyncSession,
    email: Email,
) -> dict:
    """Extract data from an email and update its database record."""
    extraction = await extract_email(session, email)

    email.extraction_result = extraction
    email.needs_reply = extraction.get("reply_needed", False)
    email.reply_suggested = extraction.get("suggested_reply")
    email.processed_at = datetime.now(timezone.utc)
    await session.flush()

    return extraction
