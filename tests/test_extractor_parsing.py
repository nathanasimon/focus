"""Tests for extractor JSON parsing — Claude Haiku responses come in many shapes."""

from src.processing.extractor import _parse_extraction, _empty_extraction


class TestParseExtraction:
    def test_clean_json(self):
        raw = '{"tasks": [{"text": "Send docs", "assigned_to": "me", "deadline": null, "priority": "normal"}], "commitments": [], "questions": [], "waiting_on": [], "project_links": ["trading-bot"], "new_projects": [], "people_mentioned": ["Sarah"], "sentiment": "neutral", "reply_needed": true, "reply_urgency": "normal", "suggested_reply": "Will do."}'
        result = _parse_extraction(raw)
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["text"] == "Send docs"
        assert result["reply_needed"] is True

    def test_markdown_code_block_json(self):
        raw = '```json\n{"tasks": [], "commitments": [], "questions": [], "waiting_on": [], "project_links": [], "new_projects": [], "people_mentioned": [], "sentiment": "neutral", "reply_needed": false, "reply_urgency": "none", "suggested_reply": null}\n```'
        result = _parse_extraction(raw)
        assert result["reply_needed"] is False

    def test_code_block_with_trailing_newline(self):
        """The bug we fixed: trailing newline after closing ``` broke old logic."""
        raw = '```json\n{"tasks": [], "commitments": [], "sentiment": "neutral", "reply_needed": false}\n```\n'
        result = _parse_extraction(raw)
        assert result["reply_needed"] is False

    def test_code_block_with_multiple_trailing_newlines(self):
        raw = '```json\n{"tasks": [], "commitments": [], "sentiment": "neutral", "reply_needed": false}\n```\n\n\n'
        result = _parse_extraction(raw)
        assert result["reply_needed"] is False

    def test_json_with_preamble(self):
        raw = 'Here is the extracted data:\n\n{"tasks": [{"text": "Review PR"}], "commitments": [], "questions": [], "waiting_on": [], "project_links": [], "new_projects": [], "people_mentioned": [], "sentiment": "neutral", "reply_needed": false, "reply_urgency": "none", "suggested_reply": null}'
        result = _parse_extraction(raw)
        assert len(result["tasks"]) == 1

    def test_empty_string_returns_empty_extraction(self):
        result = _parse_extraction("")
        assert result == _empty_extraction()

    def test_no_json_returns_empty_extraction(self):
        result = _parse_extraction("I could not extract any data from this email.")
        assert result == _empty_extraction()

    def test_truncated_json_returns_empty(self):
        result = _parse_extraction('{"tasks": [{"text": "Do stuff"')
        assert result == _empty_extraction()

    def test_nested_json_objects(self):
        raw = '{"tasks": [{"text": "Deploy", "meta": {"env": "prod"}}], "commitments": [], "sentiment": "neutral", "reply_needed": false}'
        result = _parse_extraction(raw)
        assert result["tasks"][0]["text"] == "Deploy"

    def test_unicode_content(self):
        raw = '{"tasks": [{"text": "日本語テスト"}], "commitments": [], "sentiment": "neutral", "reply_needed": false}'
        result = _parse_extraction(raw)
        assert result["tasks"][0]["text"] == "日本語テスト"


class TestEmptyExtraction:
    def test_returns_all_expected_keys(self):
        e = _empty_extraction()
        expected_keys = {
            "tasks", "commitments", "questions", "waiting_on",
            "project_links", "new_projects", "people_mentioned",
            "sentiment", "reply_needed", "reply_urgency", "suggested_reply",
        }
        assert set(e.keys()) == expected_keys

    def test_lists_are_empty(self):
        e = _empty_extraction()
        assert e["tasks"] == []
        assert e["commitments"] == []

    def test_returns_fresh_dict(self):
        e1 = _empty_extraction()
        e2 = _empty_extraction()
        e1["tasks"].append("oops")
        assert e2["tasks"] == []
