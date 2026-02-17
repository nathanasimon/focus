"""Tests for the context formatter (src/context/formatter.py)."""

import pytest

from src.context.formatter import (
    _estimate_tokens,
    _format_single_block,
    format_context_blocks,
)
from src.context.retriever import ContextBlock


class TestEstimateTokens:
    """Tests for _estimate_tokens."""

    def test_basic_estimate(self):
        """100 chars ~= 25 tokens."""
        assert _estimate_tokens("A" * 100) == 25

    def test_empty_string_returns_one(self):
        """Empty string returns minimum of 1."""
        assert _estimate_tokens("") == 1

    def test_short_string(self):
        """Short string returns 1."""
        assert _estimate_tokens("Hi") == 1


class TestFormatSingleBlock:
    """Tests for _format_single_block."""

    def test_conversation_block(self):
        block = ContextBlock("conversation", "id1", "Title", "Some content", 0.8)
        result = _format_single_block(block)
        assert "[Conv]" in result
        assert "Some content" in result

    def test_task_block(self):
        block = ContextBlock("task", "id2", "Title", "Task content", 0.6)
        result = _format_single_block(block)
        assert "[Task]" in result

    def test_email_block(self):
        block = ContextBlock("email", "id3", "Title", "Email content", 0.5)
        result = _format_single_block(block)
        assert "[Email]" in result

    def test_unknown_type_uses_title_case(self):
        block = ContextBlock("custom_type", "id4", "Title", "Content", 0.5)
        result = _format_single_block(block)
        assert "[Custom_Type]" in result


class TestFormatContextBlocks:
    """Tests for format_context_blocks."""

    def test_empty_blocks_returns_empty(self):
        assert format_context_blocks([]) == ""

    def test_single_block_formatted(self):
        blocks = [ContextBlock("task", "id1", "My Task", "Fix the bug", 0.8)]
        result = format_context_blocks(blocks)

        assert "## Focus Context" in result
        assert "[Task]" in result
        assert "Fix the bug" in result

    def test_sorts_by_relevance(self):
        blocks = [
            ContextBlock("task", "low", "Low", "Low priority", 0.2),
            ContextBlock("conversation", "high", "High", "High priority", 0.9),
        ]
        result = format_context_blocks(blocks)

        # High relevance should come first
        high_pos = result.index("High priority")
        low_pos = result.index("Low priority")
        assert high_pos < low_pos

    def test_truncates_at_token_budget(self):
        """Blocks exceeding budget are excluded with overflow note."""
        blocks = [
            ContextBlock("task", "a", "A", "A" * 400, 0.9),  # ~100 tokens
            ContextBlock("task", "b", "B", "B" * 400, 0.8),  # ~100 tokens
            ContextBlock("task", "c", "C", "C" * 400, 0.7),  # ~100 tokens
        ]

        # With budget of 50 tokens, only 1 block should fit
        # (header takes some, each block ~100)
        result = format_context_blocks(blocks, max_tokens=120)

        assert "AAAA" in result
        assert "+2 more" in result or "+1 more" in result

    def test_overflow_note_includes_count(self):
        """Overflow note shows correct count of excluded blocks."""
        blocks = [
            ContextBlock("task", f"id{i}", f"T{i}", f"Content {i}" * 20, 0.5)
            for i in range(10)
        ]

        result = format_context_blocks(blocks, max_tokens=100)

        assert "more" in result
        assert "focus search" in result

    def test_large_budget_includes_all(self):
        """Large budget includes all blocks without overflow."""
        blocks = [
            ContextBlock("task", "a", "A", "Short", 0.9),
            ContextBlock("task", "b", "B", "Also short", 0.8),
        ]

        result = format_context_blocks(blocks, max_tokens=5000)

        assert "Short" in result
        assert "Also short" in result
        assert "more" not in result

    def test_header_present(self):
        """Output starts with Focus Context header."""
        blocks = [ContextBlock("task", "a", "A", "Content", 0.5)]
        result = format_context_blocks(blocks)
        assert result.startswith("## Focus Context")
