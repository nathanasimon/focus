"""Tests for the priority calculation system — the core scoring engine.

These test the pure math logic using mock objects to avoid needing a database.
"""

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_project, make_task


# We test the scoring logic by calling the functions with mocked sessions.
# The functions need async session for sprint lookups, so we mock that.


@pytest.fixture
def mock_session():
    """Create a mock async session that returns no sprints by default."""
    session = AsyncMock()
    # Default: no sprint found
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result
    session.get.return_value = None
    return session


class TestProjectPriority:
    @pytest.mark.asyncio
    async def test_unpinned_no_deadline_baseline(self, mock_session):
        from src.priority import effective_priority_project

        project = make_project(user_pinned=False, user_priority=None, user_deadline=None,
                               mention_count=5, source_diversity=2, people_count=3)
        score = await effective_priority_project(mock_session, project)
        # Should be just activity signals: log(6)*2 + 2*3 + 3*1.5 = ~3.58 + 6 + 4.5 = ~14.08
        assert score > 0
        assert score < 50  # No pins/deadlines, so modest score

    @pytest.mark.asyncio
    async def test_pinned_gets_100(self, mock_session):
        from src.priority import effective_priority_project

        project = make_project(user_pinned=True, mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 100

    @pytest.mark.asyncio
    async def test_critical_priority_boost(self, mock_session):
        from src.priority import effective_priority_project

        project = make_project(user_priority="critical", mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 80

    @pytest.mark.asyncio
    async def test_low_priority_penalty(self, mock_session):
        from src.priority import effective_priority_project

        project = make_project(user_priority="low", mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score < 0

    @pytest.mark.asyncio
    async def test_overdue_deadline(self, mock_session):
        from src.priority import effective_priority_project

        yesterday = date.today() - timedelta(days=1)
        project = make_project(user_deadline=yesterday, mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 90  # Overdue = +90

    @pytest.mark.asyncio
    async def test_deadline_tomorrow(self, mock_session):
        from src.priority import effective_priority_project

        tomorrow = date.today() + timedelta(days=1)
        project = make_project(user_deadline=tomorrow, mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 70  # Within 3 days

    @pytest.mark.asyncio
    async def test_deadline_next_week(self, mock_session):
        from src.priority import effective_priority_project

        next_week = date.today() + timedelta(days=6)
        project = make_project(user_deadline=next_week, mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 40

    @pytest.mark.asyncio
    async def test_deadline_far_away(self, mock_session):
        from src.priority import effective_priority_project

        far = date.today() + timedelta(days=60)
        project = make_project(user_deadline=far, mention_count=0, source_diversity=0, people_count=0)
        score = await effective_priority_project(mock_session, project)
        assert score >= 5
        assert score < 20

    @pytest.mark.asyncio
    async def test_sprint_boost_on_zero_base(self, mock_session):
        """The bug we fixed: sprint boost should still elevate even when base score is 0."""
        from src.priority import effective_priority_project

        # Mock: sprint found
        sprint = MagicMock()
        sprint.priority_boost = 2.0
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sprint
        mock_session.execute.return_value = mock_result

        project = make_project(
            user_pinned=False, user_priority=None, user_deadline=None,
            mention_count=0, source_diversity=0, people_count=0,
        )
        score = await effective_priority_project(mock_session, project)
        # With the fix: max(0, 10) * 2.0 = 20.0
        assert score >= 20.0

    @pytest.mark.asyncio
    async def test_sprint_boost_multiplies_high_score(self, mock_session):
        from src.priority import effective_priority_project

        sprint = MagicMock()
        sprint.priority_boost = 2.0
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sprint
        mock_session.execute.return_value = mock_result

        project = make_project(
            user_pinned=True,  # +100
            mention_count=0, source_diversity=0, people_count=0,
        )
        score = await effective_priority_project(mock_session, project)
        assert score >= 200.0  # 100 * 2.0

    @pytest.mark.asyncio
    async def test_pinned_plus_critical_plus_overdue(self, mock_session):
        from src.priority import effective_priority_project

        yesterday = date.today() - timedelta(days=1)
        project = make_project(
            user_pinned=True, user_priority="critical", user_deadline=yesterday,
            mention_count=0, source_diversity=0, people_count=0,
        )
        score = await effective_priority_project(mock_session, project)
        # 100 + 80 + 90 = 270
        assert score >= 270


class TestTaskPriority:
    @pytest.mark.asyncio
    async def test_normal_task_baseline(self, mock_session):
        from src.priority import effective_priority_task

        task = make_task(priority="normal", user_pinned=False, user_priority=None, due_date=None)
        score = await effective_priority_task(mock_session, task)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_urgent_base_priority(self, mock_session):
        from src.priority import effective_priority_task

        task = make_task(priority="urgent")
        score = await effective_priority_task(mock_session, task)
        assert score >= 30

    @pytest.mark.asyncio
    async def test_user_priority_overrides(self, mock_session):
        from src.priority import effective_priority_task

        task = make_task(priority="low", user_priority="urgent")
        score = await effective_priority_task(mock_session, task)
        # user_priority=urgent (+80) + base priority=low (-10) = 70
        assert score >= 70

    @pytest.mark.asyncio
    async def test_overdue_task(self, mock_session):
        from src.priority import effective_priority_task

        yesterday = date.today() - timedelta(days=1)
        task = make_task(due_date=yesterday)
        score = await effective_priority_task(mock_session, task)
        assert score >= 90
