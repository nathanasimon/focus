"""Token-budget-aware context formatter for additionalContext injection."""

import logging
from typing import Optional

from src.context.retriever import ContextBlock

logger = logging.getLogger(__name__)

# Prefixes for each source type
_TYPE_LABELS = {
    "conversation": "Conv",
    "task": "Task",
    "email": "Email",
    "commitment": "Commitment",
    "person": "Person",
    "sprint": "Sprint",
    "file_context": "File",
    "error": "Error",
}


def format_context_blocks(
    blocks: list[ContextBlock],
    max_tokens: int = 1500,
) -> str:
    """Format context blocks into a concise text block for additionalContext.

    Sorts by relevance, greedily fills the token budget, and adds
    an overflow note if blocks remain.

    Args:
        blocks: Context blocks to format.
        max_tokens: Maximum token budget.

    Returns:
        Formatted string ready for additionalContext, or empty string.
    """
    if not blocks:
        return ""

    # Sort by relevance (highest first)
    sorted_blocks = sorted(blocks, key=lambda b: b.relevance_score, reverse=True)

    header = "## Focus Context\n\n"
    header_tokens = _estimate_tokens(header)
    remaining = max_tokens - header_tokens

    formatted_parts = []
    included = 0
    overflow = 0

    for block in sorted_blocks:
        formatted = _format_single_block(block)
        tokens = _estimate_tokens(formatted)

        if tokens <= remaining:
            formatted_parts.append(formatted)
            remaining -= tokens
            included += 1
        else:
            overflow += 1

    if not formatted_parts:
        return ""

    result = header + "\n".join(formatted_parts)

    if overflow > 0:
        result += f"\n\n(+{overflow} more — run `focus search` for details)"

    return result


def _format_single_block(block: ContextBlock) -> str:
    """Format one context block as a concise text line.

    Args:
        block: The block to format.

    Returns:
        Formatted string.
    """
    label = _TYPE_LABELS.get(block.source_type, block.source_type.title())
    return f"[{label}] {block.content}"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: character_count / 4.

    Conservative average for English text.

    Args:
        text: Text to estimate.

    Returns:
        Estimated token count (minimum 1).
    """
    return max(1, len(text) // 4)
