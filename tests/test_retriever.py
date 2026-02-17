"""Tests for the context retriever (src/context/retriever.py)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context.classifier import PromptClassification
from src.context.retriever import ContextBlock, ContextRetriever, _relative_time


class TestContextBlock:
    """Tests for ContextBlock."""

    def test_auto_token_estimate(self):
        """Token estimate is computed from content length."""
        block = ContextBlock(
            source_type="task",
            source_id="test",
            title="Test",
            content="A" * 100,
            relevance_score=0.5,
        )
        assert block.token_estimate == 25  # 100 / 4

    def test_min_token_estimate(self):
        """Token estimate is at least 1."""
        block = ContextBlock(
            source_type="task",
            source_id="test",
            title="Test",
            content="Hi",
            relevance_score=0.5,
        )
        assert block.token_estimate >= 1


class TestRelativeTime:
    """Tests for _relative_time."""

    def test_just_now(self):
        dt = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert _relative_time(dt) == "just now"

    def test_minutes(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert "5m ago" == _relative_time(dt)

    def test_hours(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=3)
        assert "3h ago" == _relative_time(dt)

    def test_days(self):
        dt = datetime.now(timezone.utc) - timedelta(days=2)
        assert "2d ago" == _relative_time(dt)

    def test_weeks(self):
        dt = datetime.now(timezone.utc) - timedelta(weeks=3)
        assert "3w ago" == _relative_time(dt)

    def test_none_returns_unknown(self):
        assert _relative_time(None) == "unknown time"

    def test_naive_datetime_handled(self):
        dt = datetime.now() - timedelta(hours=1)
        result = _relative_time(dt)
        assert "ago" in result


class TestContextRetriever:
    """Tests for ContextRetriever."""

    @pytest.mark.asyncio
    async def test_low_confidence_returns_empty(self):
        """Classification with confidence < 0.1 returns no blocks."""
        retriever = ContextRetriever()
        session = AsyncMock()

        classification = PromptClassification(confidence=0.05)
        blocks = await retriever.retrieve(session, classification)

        assert blocks == []

    @pytest.mark.asyncio
    async def test_deduplicates_blocks(self):
        """Blocks with same source_id are deduplicated."""
        retriever = ContextRetriever()
        session = AsyncMock()

        # Mock all internal methods to return blocks with duplicate IDs
        block1 = ContextBlock("task", "same-id", "T1", "content1", 0.8)
        block2 = ContextBlock("task", "same-id", "T2", "content2", 0.6)
        block3 = ContextBlock("task", "other-id", "T3", "content3", 0.5)

        retriever._get_recent_turns = AsyncMock(return_value=[block1])
        retriever._get_active_tasks = AsyncMock(return_value=[block2, block3])
        retriever._get_open_commitments = AsyncMock(return_value=[])
        retriever._get_active_sprints = AsyncMock(return_value=[])

        # Mock project resolution
        mock_proj_result = MagicMock()
        mock_proj_result.all.return_value = [(uuid.uuid4(), "focus")]
        session.execute = AsyncMock(return_value=mock_proj_result)

        classification = PromptClassification(
            project_slugs=["focus"],
            confidence=0.8,
        )

        blocks = await retriever.retrieve(session, classification)

        source_ids = [b.source_id for b in blocks]
        assert len(source_ids) == len(set(source_ids))  # No duplicates

    @pytest.mark.asyncio
    async def test_sorts_by_relevance(self):
        """Blocks are sorted by relevance score descending."""
        retriever = ContextRetriever()
        session = AsyncMock()

        block_low = ContextBlock("task", "a", "Low", "low", 0.2)
        block_high = ContextBlock("task", "b", "High", "high", 0.9)
        block_mid = ContextBlock("task", "c", "Mid", "mid", 0.5)

        retriever._get_recent_turns = AsyncMock(return_value=[block_low])
        retriever._get_active_tasks = AsyncMock(return_value=[block_high])
        retriever._get_open_commitments = AsyncMock(return_value=[block_mid])
        retriever._get_active_sprints = AsyncMock(return_value=[])

        mock_proj_result = MagicMock()
        mock_proj_result.all.return_value = [(uuid.uuid4(), "focus")]
        session.execute = AsyncMock(return_value=mock_proj_result)

        classification = PromptClassification(
            project_slugs=["focus"],
            confidence=0.8,
        )

        blocks = await retriever.retrieve(session, classification)

        scores = [b.relevance_score for b in blocks]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_workspace_fallback(self):
        """When no project slug but workspace match, uses workspace path."""
        retriever = ContextRetriever()
        session = AsyncMock()

        retriever._get_recent_turns = AsyncMock(return_value=[])
        retriever._get_active_sprints = AsyncMock(return_value=[])
        retriever._get_open_commitments = AsyncMock(return_value=[])

        # No project matched by slug
        mock_proj_result = MagicMock()
        mock_proj_result.first.return_value = None
        session.execute = AsyncMock(return_value=mock_proj_result)

        classification = PromptClassification(
            workspace_project="myproject",
            confidence=0.5,
        )

        await retriever.retrieve(session, classification)

        # Should have called _get_recent_turns with workspace_path_like
        calls = retriever._get_recent_turns.call_args_list
        workspace_calls = [c for c in calls if c[1].get("workspace_path_like") == "myproject"]
        assert len(workspace_calls) == 1
