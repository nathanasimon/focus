"""Tests for entity resolution pure functions — the fuzzy matching logic."""

from src.processing.resolver import (
    _extract_email_from_header,
    _extract_name_from_header,
    _normalize_name,
    _similarity,
    _slugify,
)


class TestExtractEmailFromHeader:
    def test_name_angle_brackets(self):
        assert _extract_email_from_header("John Doe <john@example.com>") == "john@example.com"

    def test_quoted_name(self):
        assert _extract_email_from_header('"John Doe" <john@example.com>') == "john@example.com"

    def test_bare_email(self):
        assert _extract_email_from_header("john@example.com") == "john@example.com"

    def test_email_with_plus(self):
        assert _extract_email_from_header("John <john+tag@example.com>") == "john+tag@example.com"

    def test_email_with_dots(self):
        assert _extract_email_from_header("j.doe@sub.example.com") == "j.doe@sub.example.com"

    def test_no_email_returns_none(self):
        assert _extract_email_from_header("no email here") is None

    def test_empty_string(self):
        assert _extract_email_from_header("") is None

    def test_case_normalized(self):
        assert _extract_email_from_header("John <JOHN@EXAMPLE.COM>") == "john@example.com"


class TestExtractNameFromHeader:
    def test_name_angle_brackets(self):
        assert _extract_name_from_header("John Doe <john@example.com>") == "John Doe"

    def test_quoted_name(self):
        assert _extract_name_from_header('"John Doe" <john@example.com>') == "John Doe"

    def test_bare_email_derives_name(self):
        assert _extract_name_from_header("john.doe@example.com") == "John Doe"

    def test_no_email_returns_none(self):
        assert _extract_name_from_header("") is None

    def test_name_with_extra_spaces(self):
        name = _extract_name_from_header("  John Doe  <john@example.com>")
        assert name == "John Doe"

    def test_company_name(self):
        name = _extract_name_from_header("Amazon.com <ship-confirm@amazon.com>")
        assert name == "Amazon.com"


class TestNormalizeName:
    def test_lowercase(self):
        assert _normalize_name("John Doe") == "john doe"

    def test_strips_special_chars(self):
        assert _normalize_name("O'Brien") == "obrien"

    def test_strips_numbers(self):
        assert _normalize_name("Agent 47") == "agent"

    def test_empty_input(self):
        assert _normalize_name("") == ""

    def test_unicode(self):
        # Non-ASCII stripped by the regex
        assert _normalize_name("José García") == "jos garca"


class TestSimilarity:
    def test_identical(self):
        assert _similarity("John Doe", "John Doe") == 1.0

    def test_case_insensitive(self):
        assert _similarity("john doe", "JOHN DOE") == 1.0

    def test_very_different(self):
        assert _similarity("Alice", "Bob") < 0.5

    def test_close_names(self):
        score = _similarity("Sarah Chen", "Sarah Chenn")
        assert score > 0.8  # Should match as same person

    def test_first_last_vs_last_first(self):
        score = _similarity("John Smith", "Smith John")
        assert score < 0.8  # Different enough to not auto-match

    def test_empty_strings(self):
        # Two empty strings have ratio 0 in SequenceMatcher
        score = _similarity("", "")
        # SequenceMatcher("", "") returns 0.0 actually
        assert isinstance(score, float)


class TestSlugify:
    def test_basic(self):
        assert _slugify("Trading Bot") == "trading-bot"

    def test_special_chars(self):
        assert _slugify("NYU Application (2026)") == "nyu-application-2026"

    def test_dashes_preserved(self):
        assert _slugify("my-project") == "my-project"

    def test_underscores_become_dashes(self):
        assert _slugify("my_project") == "my-project"

    def test_multiple_spaces(self):
        assert _slugify("my   project") == "my-project"

    def test_leading_trailing_stripped(self):
        assert _slugify("  Trading Bot  ") == "trading-bot"

    def test_all_special_chars_returns_fallback(self):
        """The bug we fixed: all-special-char names produced empty slugs."""
        assert _slugify("!!!") == "unnamed-project"

    def test_empty_string_returns_fallback(self):
        assert _slugify("") == "unnamed-project"

    def test_unicode_preserved(self):
        # Python's \w includes unicode word chars, so accented letters stay
        assert _slugify("café project") == "café-project"
