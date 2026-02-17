"""Claude Code session capture — ingest decisions and context from Claude Code sessions."""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import RawInteraction
from src.storage.raw import store_raw_interaction

logger = logging.getLogger(__name__)

# Default location for Claude Code session files
CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "projects"

# Decision extraction prompt for Claude Haiku
DECISION_EXTRACTION_SYSTEM = """You extract decisions from Claude Code session transcripts.

A "decision" is a deliberate choice about architecture, design, implementation approach,
library selection, naming, or other technical matter that was discussed and resolved.

Return ONLY valid JSON — a list of decision objects:
[
  {
    "decision": "Short summary of what was decided",
    "context": "Why this came up / what problem it solves",
    "trade_off": "What was considered but rejected, or what was traded away",
    "date": "ISO date if known, else null",
    "tags": ["relevant", "topic", "tags"]
  }
]

Be conservative — only extract clear decisions, not every statement.
If there are no decisions in the transcript, return [].
"""


def parse_session_file(path: Path) -> list[dict]:
    """Parse a Claude Code JSONL session file into conversation turns.

    Returns list of dicts with keys: role, content, timestamp, type.
    Filters to meaningful user/assistant text messages only.
    """
    turns = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            if msg_type not in ("user", "assistant"):
                continue

            # Skip sidechain (subagent) messages
            if obj.get("isSidechain"):
                continue

            # Skip meta messages (system/command)
            if obj.get("isMeta"):
                continue

            message = obj.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            timestamp = obj.get("timestamp", "")
            content_text = _extract_text_content(message.get("content", ""))

            if not content_text or len(content_text.strip()) < 10:
                continue

            # Skip command messages
            if content_text.strip().startswith("<command-name>"):
                continue
            if content_text.strip().startswith("<local-command"):
                continue

            turns.append({
                "role": role,
                "content": content_text,
                "timestamp": timestamp,
                "session_id": obj.get("sessionId", ""),
            })

    return turns


def _extract_text_content(content) -> str:
    """Extract plain text from a message content field.

    Content can be a string (user messages) or a list of content blocks
    (assistant messages with text/tool_use/tool_result blocks).
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        return "\n".join(text_parts)

    return ""


def build_session_summary(turns: list[dict], max_chars: int = 8000) -> str:
    """Build a condensed transcript from conversation turns.

    Truncates to max_chars to fit within LLM context for decision extraction.
    """
    parts = []
    total = 0

    for turn in turns:
        role = turn["role"].upper()
        content = turn["content"]

        # Truncate individual messages
        if len(content) > 1000:
            content = content[:1000] + "..."

        entry = f"[{role}]: {content}"
        if total + len(entry) > max_chars:
            break

        parts.append(entry)
        total += len(entry)

    return "\n\n".join(parts)


def get_session_metadata(path: Path, turns: list[dict]) -> dict:
    """Extract metadata from a session file and its turns."""
    session_id = path.stem  # UUID filename without .jsonl

    # Parse project directory from path
    # Format: ~/.claude/projects/-home-user-projectname/session.jsonl
    project_dir = path.parent.name

    # Extract timestamps
    timestamps = [t["timestamp"] for t in turns if t.get("timestamp")]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None

    return {
        "session_id": session_id,
        "project_dir": project_dir,
        "turn_count": len(turns),
        "user_turns": sum(1 for t in turns if t["role"] == "user"),
        "assistant_turns": sum(1 for t in turns if t["role"] == "assistant"),
        "start_time": start_time,
        "end_time": end_time,
    }


async def extract_decisions(
    session: AsyncSession,
    transcript: str,
) -> list[dict]:
    """Use Claude Haiku to extract decisions from a session transcript.

    Returns list of decision dicts, empty list on failure or if no decisions.
    """
    from src.config import get_settings

    settings = get_settings()

    if not settings.anthropic.api_key:
        logger.warning("No Anthropic API key, skipping decision extraction")
        return []

    try:
        import anthropic
        import time

        client = anthropic.Anthropic(api_key=settings.anthropic.api_key)

        start_time = time.time()
        response = client.messages.create(
            model=settings.anthropic.model,
            max_tokens=2000,
            system=DECISION_EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": f"Extract decisions from this Claude Code session:\n\n{transcript}"}],
        )

        latency_ms = int((time.time() - start_time) * 1000)
        raw_text = response.content[0].text

        # Log the AI call
        if settings.raw_storage.store_ai_conversations:
            from src.storage.raw import store_ai_conversation

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost_usd = (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

            await store_ai_conversation(
                session=session,
                session_type="claude_code_decision_extraction",
                model=settings.anthropic.model,
                request_messages=[
                    {"role": "system", "content": DECISION_EXTRACTION_SYSTEM},
                    {"role": "user", "content": f"[transcript: {len(transcript)} chars]"},
                ],
                response_content={"raw": raw_text},
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )

        return _parse_decisions(raw_text)

    except Exception as e:
        logger.error("Decision extraction failed: %s", e)
        return []


def _parse_decisions(raw_text: str) -> list[dict]:
    """Parse the JSON decision list from Claude's response."""
    try:
        text = raw_text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

        # Find the JSON array
        start = text.index("[")
        end = text.rindex("]") + 1
        decisions = json.loads(text[start:end])

        if not isinstance(decisions, list):
            return []

        # Validate each decision has required fields
        valid = []
        for d in decisions:
            if isinstance(d, dict) and d.get("decision"):
                valid.append({
                    "decision": d["decision"],
                    "context": d.get("context", ""),
                    "trade_off": d.get("trade_off", ""),
                    "date": d.get("date"),
                    "tags": d.get("tags", []),
                })
        return valid

    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse decisions JSON: %s", raw_text[:200])
        return []


async def ingest_session(
    session: AsyncSession,
    path: Path,
    extract: bool = True,
) -> dict:
    """Ingest a single Claude Code session file.

    Args:
        session: Database session.
        path: Path to the .jsonl session file.
        extract: Whether to extract decisions using Haiku.

    Returns:
        Dict with session_id, turns, decisions_count.
    """
    turns = parse_session_file(path)
    if not turns:
        return {"session_id": path.stem, "turns": 0, "decisions_count": 0}

    metadata = get_session_metadata(path, turns)
    transcript = build_session_summary(turns)

    # Store raw interaction
    await store_raw_interaction(
        session=session,
        source_type="claude_code_session",
        raw_content=transcript,
        source_id=metadata["session_id"],
        raw_metadata=metadata,
        interaction_date=_parse_timestamp(metadata.get("start_time")),
    )

    # Extract decisions
    decisions = []
    if extract and len(turns) >= 3:  # Only extract from substantial sessions
        decisions = await extract_decisions(session, transcript)

        if decisions:
            # Store decisions as a separate raw interaction for the archive
            await store_raw_interaction(
                session=session,
                source_type="claude_code_decisions",
                raw_content=json.dumps(decisions, indent=2),
                source_id=f"{metadata['session_id']}_decisions",
                raw_metadata={
                    **metadata,
                    "decision_count": len(decisions),
                },
                interaction_date=_parse_timestamp(metadata.get("end_time")),
            )

    logger.info(
        "Ingested session %s: %d turns, %d decisions",
        metadata["session_id"][:12],
        len(turns),
        len(decisions),
    )

    return {
        "session_id": metadata["session_id"],
        "turns": len(turns),
        "decisions_count": len(decisions),
        "decisions": decisions,
    }


async def scan_sessions(
    session: AsyncSession,
    project_dir: Optional[str] = None,
    extract: bool = True,
) -> dict:
    """Scan for new Claude Code sessions and ingest them.

    Args:
        session: Database session.
        project_dir: Specific project directory name to scan.
            If None, scans all projects under ~/.claude/projects/.
        extract: Whether to extract decisions.

    Returns:
        Summary dict with counts.
    """
    summary = {"sessions_found": 0, "sessions_ingested": 0, "sessions_skipped": 0, "total_decisions": 0}

    base_dir = CLAUDE_SESSIONS_DIR
    if not base_dir.exists():
        logger.info("No Claude Code sessions directory found at %s", base_dir)
        return summary

    # Collect all JSONL files
    if project_dir:
        search_dirs = [base_dir / project_dir]
    else:
        search_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

    for dir_path in search_dirs:
        if not dir_path.exists():
            continue

        for jsonl_file in sorted(dir_path.glob("*.jsonl")):
            summary["sessions_found"] += 1
            session_id = jsonl_file.stem

            # Check if already ingested (by source_id)
            existing = await session.execute(
                select(RawInteraction).where(
                    RawInteraction.source_type == "claude_code_session",
                    RawInteraction.source_id == session_id,
                )
            )
            if existing.scalar_one_or_none():
                summary["sessions_skipped"] += 1
                continue

            try:
                result = await ingest_session(session, jsonl_file, extract=extract)
                if result["turns"] > 0:
                    summary["sessions_ingested"] += 1
                    summary["total_decisions"] += result["decisions_count"]
                else:
                    summary["sessions_skipped"] += 1
            except Exception as e:
                logger.error("Failed to ingest session %s: %s", session_id[:12], e)

    logger.info(
        "Session scan: %d found, %d ingested, %d skipped, %d decisions",
        summary["sessions_found"],
        summary["sessions_ingested"],
        summary["sessions_skipped"],
        summary["total_decisions"],
    )
    return summary


def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def compute_content_hash(content: str) -> str:
    """Compute MD5 hash for content deduplication.

    Args:
        content: Text content to hash.

    Returns:
        Hex digest of MD5 hash.
    """
    return hashlib.md5(content.encode()).hexdigest()


def _extract_tool_names(content) -> list[str]:
    """Extract tool names from assistant message content blocks.

    Args:
        content: Message content (string or list of blocks).

    Returns:
        List of unique tool names used in this message.
    """
    if not isinstance(content, list):
        return []

    tools = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "")
            if name and name not in tools:
                tools.append(name)
    return tools


def parse_session_into_turns(path: Path) -> list[dict]:
    """Parse a Claude Code JSONL session file into structured turns.

    A "turn" is a user message followed by the assistant's complete response
    (which may include tool calls, thinking, and text blocks).

    Args:
        path: Path to the .jsonl session file.

    Returns:
        List of turn dicts with keys: turn_number, user_message,
        assistant_text, tool_names, model_name, started_at, ended_at,
        raw_jsonl, content_hash.
    """
    if not path.exists():
        return []

    # First pass: collect all non-sidechain, non-meta messages
    messages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            if msg_type not in ("user", "assistant"):
                continue

            if obj.get("isSidechain") or obj.get("isMeta"):
                continue

            message = obj.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = message.get("content", "")
            text_content = _extract_text_content(content)

            # Skip command messages
            if text_content and text_content.strip().startswith(("<command-name>", "<local-command")):
                continue

            messages.append({
                "role": role,
                "content": content,
                "text": text_content,
                "timestamp": obj.get("timestamp", ""),
                "model": message.get("model", ""),
                "raw_line": line,
            })

    # Second pass: group into turns (user message + assistant responses)
    turns = []
    current_turn: Optional[dict] = None

    for msg in messages:
        if msg["role"] == "user":
            # Start a new turn
            if current_turn and current_turn.get("user_message"):
                _finalize_turn(current_turn, len(turns))
                turns.append(current_turn)

            current_turn = {
                "user_message": msg["text"],
                "assistant_texts": [],
                "tool_names": [],
                "model_name": None,
                "started_at": msg["timestamp"],
                "ended_at": msg["timestamp"],
                "raw_lines": [msg["raw_line"]],
            }
        elif msg["role"] == "assistant" and current_turn is not None:
            # Append to current turn
            if msg["text"]:
                current_turn["assistant_texts"].append(msg["text"])
            tools = _extract_tool_names(msg["content"])
            for t in tools:
                if t not in current_turn["tool_names"]:
                    current_turn["tool_names"].append(t)
            if msg["model"] and not current_turn["model_name"]:
                current_turn["model_name"] = msg["model"]
            current_turn["ended_at"] = msg["timestamp"] or current_turn["ended_at"]
            current_turn["raw_lines"].append(msg["raw_line"])

    # Finalize last turn
    if current_turn and current_turn.get("user_message"):
        _finalize_turn(current_turn, len(turns))
        turns.append(current_turn)

    return turns


def _finalize_turn(turn: dict, index: int) -> None:
    """Finalize a turn dict by computing hash and cleaning up fields.

    Args:
        turn: Mutable turn dict to finalize in place.
        index: Zero-based turn index.
    """
    raw_jsonl = "\n".join(turn.pop("raw_lines"))
    assistant_text = "\n".join(turn.pop("assistant_texts"))

    turn["turn_number"] = index
    turn["assistant_text"] = assistant_text
    turn["raw_jsonl"] = raw_jsonl
    turn["content_hash"] = compute_content_hash(raw_jsonl)
