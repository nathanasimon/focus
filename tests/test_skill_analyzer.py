"""Tests for src/skills/analyzer.py."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.skills.analyzer import (
    SkillCandidate,
    _compute_description_hash,
    analyze_session_for_skill,
    extract_skill_pattern,
    score_session_quality,
)


class TestScoreSessionQuality:
    def test_high_quality_session(self):
        score = score_session_quality(
            turn_count=10,
            error_count=0,
            files_touched=["a.py", "b.py", "c.py", "d.py", "e.py"],
            tools_used=["Read", "Write", "Bash", "Grep"],
            has_summary=True,
        )
        assert score >= 0.6

    def test_low_turn_count(self):
        score = score_session_quality(
            turn_count=1,
            error_count=0,
            files_touched=["a.py"],
            tools_used=["Read"],
            has_summary=True,
        )
        assert score < 0.6

    def test_many_errors(self):
        score_clean = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "b.py"],
            tools_used=["Read", "Write"],
            has_summary=True,
        )
        score_errors = score_session_quality(
            turn_count=5,
            error_count=4,
            files_touched=["a.py", "b.py"],
            tools_used=["Read", "Write"],
            has_summary=True,
        )
        assert score_errors < score_clean

    def test_no_files_touched(self):
        score_no_files = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=[],
            tools_used=["Read"],
            has_summary=True,
        )
        score_with_files = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "b.py", "c.py"],
            tools_used=["Read"],
            has_summary=True,
        )
        assert score_no_files < score_with_files

    def test_zero_turns(self):
        score = score_session_quality(
            turn_count=0,
            error_count=0,
            files_touched=[],
            tools_used=[],
            has_summary=False,
        )
        assert score == 0.0

    def test_capped_at_one(self):
        score = score_session_quality(
            turn_count=100,
            error_count=0,
            files_touched=["a.py"] * 50,
            tools_used=["Read", "Write", "Bash", "Grep", "Glob", "Edit", "Search", "Task"],
            has_summary=True,
        )
        assert score <= 1.0

    def test_deduplicates_files(self):
        # Same file multiple times shouldn't inflate score
        score_dup = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "a.py", "a.py"],
            tools_used=["Read"],
            has_summary=True,
        )
        score_unique = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "b.py", "c.py"],
            tools_used=["Read"],
            has_summary=True,
        )
        assert score_unique > score_dup

    def test_no_summary_reduces_score(self):
        score_with = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "b.py"],
            tools_used=["Read", "Write"],
            has_summary=True,
        )
        score_without = score_session_quality(
            turn_count=5,
            error_count=0,
            files_touched=["a.py", "b.py"],
            tools_used=["Read", "Write"],
            has_summary=False,
        )
        assert score_with > score_without


class TestComputeDescriptionHash:
    def test_consistent(self):
        h1 = _compute_description_hash("deploy the app")
        h2 = _compute_description_hash("deploy the app")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = _compute_description_hash("Deploy The App")
        h2 = _compute_description_hash("deploy the app")
        assert h1 == h2

    def test_whitespace_normalized(self):
        h1 = _compute_description_hash("deploy  the   app")
        h2 = _compute_description_hash("deploy the app")
        assert h1 == h2

    def test_different_strings_differ(self):
        h1 = _compute_description_hash("deploy the app")
        h2 = _compute_description_hash("test the app")
        assert h1 != h2


class TestAnalyzeSessionForSkill:
    def _make_mock_session(
        self,
        session_id="test-session-123",
        is_processed=True,
        session_summary="Built a deployment pipeline",
        turn_count=5,
    ):
        session = MagicMock()
        session.id = uuid.uuid4()
        session.session_id = session_id
        session.is_processed = is_processed
        session.session_summary = session_summary
        session.workspace_path = "/home/user/project"
        session.turn_count = turn_count
        return session

    def _make_mock_turn(
        self,
        turn_number=1,
        tool_names=None,
        files_touched=None,
        commands_run=None,
        errors_encountered=None,
    ):
        turn = MagicMock()
        turn.turn_number = turn_number
        turn.tool_names = tool_names or ["Read", "Write"]
        turn.content = MagicMock()
        turn.content.files_touched = files_touched or ["src/main.py"]
        turn.content.commands_run = commands_run or ["pytest"]
        turn.content.errors_encountered = errors_encountered or []
        return turn

    @pytest.mark.asyncio
    async def test_not_processed_returns_none(self):
        agent_session = self._make_mock_session(is_processed=False)
        mock_settings = MagicMock()
        mock_settings.skills.auto_generate = True

        with patch("src.skills.analyzer.get_settings", return_value=mock_settings):
            db_session = AsyncMock()
            result = await analyze_session_for_skill(db_session, agent_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_auto_generate_disabled_returns_none(self):
        agent_session = self._make_mock_session()
        mock_settings = MagicMock()
        mock_settings.skills.auto_generate = False

        with patch("src.skills.analyzer.get_settings", return_value=mock_settings):
            db_session = AsyncMock()
            result = await analyze_session_for_skill(db_session, agent_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_daily_limit_returns_none(self):
        agent_session = self._make_mock_session()
        mock_settings = MagicMock()
        mock_settings.skills.auto_generate = True
        mock_settings.skills.max_auto_skills_per_day = 3
        mock_settings.skills.min_quality_score = 0.6

        with patch("src.skills.analyzer.get_settings", return_value=mock_settings), \
             patch("src.skills.analyzer._count_todays_auto_skills", return_value=3):
            db_session = AsyncMock()
            result = await analyze_session_for_skill(db_session, agent_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_low_quality_returns_none(self):
        agent_session = self._make_mock_session()
        mock_settings = MagicMock()
        mock_settings.skills.auto_generate = True
        mock_settings.skills.max_auto_skills_per_day = 10
        mock_settings.skills.min_quality_score = 0.99  # Very high threshold

        # Return single turn with no meaningful data
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [self._make_mock_turn(files_touched=[], tool_names=[])]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        db_session = AsyncMock()
        db_session.execute.return_value = mock_result

        with patch("src.skills.analyzer.get_settings", return_value=mock_settings), \
             patch("src.skills.analyzer._count_todays_auto_skills", return_value=0):
            result = await analyze_session_for_skill(db_session, agent_session)
            assert result is None
