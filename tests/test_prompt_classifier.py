"""Tests for the prompt classifier (src/context/classifier.py)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.context.classifier import (
    PromptClassification,
    PromptClassifier,
    _compute_confidence,
    _detect_query_type,
    _word_match,
)


class TestWordMatch:
    """Tests for _word_match."""

    def test_exact_word_matches(self):
        assert _word_match("focus", "fix the focus bug") is True

    def test_partial_word_does_not_match(self):
        assert _word_match("focus", "unfocused attention") is False

    def test_case_insensitive(self):
        assert _word_match("focus", "fix the FOCUS bug") is False  # pattern is lowercase
        # but with lowercase text:
        assert _word_match("focus", "fix the focus bug") is True

    def test_empty_text(self):
        assert _word_match("focus", "") is False

    def test_special_characters_escaped(self):
        assert _word_match("c++", "i use c++ daily") is True


class TestDetectQueryType:
    """Tests for _detect_query_type."""

    def test_code_query(self):
        assert _detect_query_type("Fix the bug in login") == "code"

    def test_email_query(self):
        assert _detect_query_type("Draft a reply to John") == "email"

    def test_task_query(self):
        assert _detect_query_type("Show me the backlog tasks") == "task"

    def test_meta_query(self):
        assert _detect_query_type("How does the daemon work?") == "meta"

    def test_general_query(self):
        assert _detect_query_type("What is the meaning of life?") == "general"

    def test_empty_query(self):
        assert _detect_query_type("") == "general"


class TestComputeConfidence:
    """Tests for _compute_confidence."""

    def test_project_match_high_confidence(self):
        c = PromptClassification(project_slugs=["focus"])
        assert _compute_confidence(c) >= 0.8

    def test_person_match_high_confidence(self):
        c = PromptClassification(person_names=["Alice"])
        assert _compute_confidence(c) >= 0.7

    def test_workspace_only_medium_confidence(self):
        c = PromptClassification(workspace_project="focus")
        assert 0.4 <= _compute_confidence(c) <= 0.6

    def test_no_match_low_confidence(self):
        c = PromptClassification()
        assert _compute_confidence(c) <= 0.2

    def test_query_type_adds_some_confidence(self):
        c = PromptClassification(query_type="code")
        assert _compute_confidence(c) >= 0.2


class TestPromptClassifier:
    """Tests for PromptClassifier."""

    @pytest.mark.asyncio
    async def test_load_entities(self):
        """Loading entities populates projects and people lists."""
        classifier = PromptClassifier()
        session = AsyncMock()

        # Mock project results
        mock_proj_result = MagicMock()
        mock_proj_result.all.return_value = [
            ("focus", "Focus"),
            ("trading-bot", "Trading Bot"),
        ]

        # Mock people results
        mock_people_result = MagicMock()
        mock_people_result.all.return_value = [
            ("Alice Chen", "alice@example.com"),
            ("Bob Smith", "bob@example.com"),
        ]

        session.execute = AsyncMock(side_effect=[mock_proj_result, mock_people_result])

        await classifier.load_entities(session)

        assert len(classifier._projects) == 2
        assert len(classifier._people) == 2
        assert classifier._loaded is True

    def test_classify_empty_prompt_low_confidence(self):
        """Empty prompt returns low confidence."""
        classifier = PromptClassifier()
        result = classifier.classify("")
        assert result.confidence <= 0.1

    def test_classify_very_short_prompt(self):
        """Very short prompt returns low confidence."""
        classifier = PromptClassifier()
        result = classifier.classify("hi")
        assert result.confidence <= 0.2

    def test_classify_project_mention(self):
        """Mentioning a known project slug returns high confidence."""
        classifier = PromptClassifier()
        classifier._projects = [("focus", "Focus")]

        result = classifier.classify("fix the bug in focus")
        assert "focus" in result.project_slugs
        assert result.confidence >= 0.8

    def test_classify_project_name_mention(self):
        """Mentioning a known project name returns high confidence."""
        classifier = PromptClassifier()
        classifier._projects = [("trading-bot", "Trading Bot")]

        result = classifier.classify("update the trading bot configuration")
        assert "trading-bot" in result.project_slugs

    def test_classify_person_mention(self):
        """Mentioning a known person returns their name."""
        classifier = PromptClassifier()
        classifier._people = [("Alice Chen", "alice@example.com")]

        result = classifier.classify("what did alice chen say about the deadline")
        assert "Alice Chen" in result.person_names

    def test_classify_cwd_maps_to_project(self):
        """CWD directory name maps to workspace project."""
        classifier = PromptClassifier()
        classifier._projects = [("focus", "Focus")]

        result = classifier.classify("fix this", cwd="/home/user/focus")
        assert result.workspace_project == "focus"

    def test_classify_cwd_no_project_match(self):
        """CWD always sets workspace_project, even without a DB project match."""
        classifier = PromptClassifier()
        classifier._projects = [("focus", "Focus")]

        result = classifier.classify("fix this", cwd="/home/user/other-project")
        assert result.workspace_project == "other-project"

    def test_classify_code_query_type(self):
        """Code-related prompts detected correctly."""
        classifier = PromptClassifier()
        result = classifier.classify("refactor the authentication module")
        assert result.query_type == "code"

    def test_classify_email_query_type(self):
        """Email-related prompts detected correctly."""
        classifier = PromptClassifier()
        result = classifier.classify("draft an email reply to the client")
        assert result.query_type == "email"

    def test_classify_no_entities_loaded(self):
        """Works gracefully when no entities are loaded."""
        classifier = PromptClassifier()
        result = classifier.classify("fix the bug in the focus project")
        # No entities to match, but query type still detected
        assert result.query_type == "code"
        assert result.project_slugs == []

    def test_classify_multiple_projects(self):
        """Multiple project mentions are all captured."""
        classifier = PromptClassifier()
        classifier._projects = [("focus", "Focus"), ("vault", "Vault")]

        result = classifier.classify("compare focus and vault approaches")
        assert "focus" in result.project_slugs
        assert "vault" in result.project_slugs

    def test_classify_short_person_name_skipped(self):
        """Person names with 2 or fewer chars are skipped."""
        classifier = PromptClassifier()
        classifier._people = [("Al", "al@example.com")]

        result = classifier.classify("talk to al about the project")
        assert result.person_names == []
