"""Tests for classifier JSON parsing and pre-classification heuristics."""

from tests.conftest import make_email
from src.processing.classifier import _parse_classification, _default_classification, pre_classify


class TestParseClassification:
    """Test _parse_classification against every shape of LLM output we've seen."""

    def test_clean_json(self):
        raw = '{"classification": "human", "confidence": 0.94, "urgency": "normal", "sender_type": "known"}'
        result = _parse_classification(raw)
        assert result["classification"] == "human"
        assert result["confidence"] == 0.94
        assert result["route_to"] == "deep_analysis"

    def test_json_with_surrounding_text(self):
        raw = 'Here is the classification:\n{"classification": "automated", "confidence": 0.88, "urgency": "low", "sender_type": "company"}\nDone.'
        result = _parse_classification(raw)
        assert result["classification"] == "automated"
        assert result["route_to"] == "regex_parse"

    def test_newsletter_routing(self):
        raw = '{"classification": "newsletter", "confidence": 0.91, "urgency": "low", "sender_type": "company"}'
        result = _parse_classification(raw)
        assert result["route_to"] == "archive"

    def test_spam_routing(self):
        raw = '{"classification": "spam", "confidence": 0.99, "urgency": "low", "sender_type": "unknown"}'
        result = _parse_classification(raw)
        assert result["route_to"] == "skip"

    def test_system_routing(self):
        raw = '{"classification": "system", "confidence": 0.95, "urgency": "normal", "sender_type": "company"}'
        result = _parse_classification(raw)
        assert result["route_to"] == "skip"

    def test_invalid_classification_defaults_to_newsletter(self):
        raw = '{"classification": "marketing", "confidence": 0.7, "urgency": "normal", "sender_type": "known"}'
        result = _parse_classification(raw)
        assert result["classification"] == "newsletter"
        assert result["confidence"] == 0.0
        assert result["route_to"] == "archive"

    def test_invalid_urgency_defaults_to_normal(self):
        raw = '{"classification": "human", "confidence": 0.8, "urgency": "medium", "sender_type": "known"}'
        result = _parse_classification(raw)
        assert result["urgency"] == "normal"

    def test_invalid_sender_type_defaults_to_unknown(self):
        raw = '{"classification": "human", "confidence": 0.8, "urgency": "normal", "sender_type": "friend"}'
        result = _parse_classification(raw)
        assert result["sender_type"] == "unknown"

    def test_empty_response_returns_default(self):
        result = _parse_classification("")
        assert result == _default_classification()

    def test_no_json_returns_default(self):
        result = _parse_classification("I cannot classify this email because reasons.")
        assert result == _default_classification()

    def test_truncated_json_returns_default(self):
        result = _parse_classification('{"classification": "huma')
        assert result == _default_classification()

    def test_json_with_newlines_inside(self):
        raw = '{\n  "classification": "human",\n  "confidence": 0.9,\n  "urgency": "urgent",\n  "sender_type": "known"\n}'
        result = _parse_classification(raw)
        assert result["classification"] == "human"
        assert result["urgency"] == "urgent"

    def test_json_with_extra_fields_still_works(self):
        raw = '{"classification": "human", "confidence": 0.9, "urgency": "normal", "sender_type": "known", "extra_field": true}'
        result = _parse_classification(raw)
        assert result["classification"] == "human"
        assert result["route_to"] == "deep_analysis"

    def test_json_missing_confidence_still_works(self):
        raw = '{"classification": "automated", "urgency": "low", "sender_type": "company"}'
        result = _parse_classification(raw)
        assert result["classification"] == "automated"
        assert result["route_to"] == "regex_parse"

    def test_multiple_json_objects_takes_first(self):
        """If LLM outputs multiple JSON blobs, we take from first { to last } — which may fail parse.
        This is a known edge case; we fall back to default."""
        raw = '{"classification": "human"} and also {"classification": "spam"}'
        result = _parse_classification(raw)
        # This will try to parse '{"classification": "human"} and also {"classification": "spam"}'
        # which is invalid JSON, so we fall back to default
        assert result == _default_classification()

    def test_markdown_code_block_json(self):
        raw = '```json\n{"classification": "human", "confidence": 0.9, "urgency": "normal", "sender_type": "known"}\n```'
        result = _parse_classification(raw)
        assert result["classification"] == "human"

    def test_route_to_always_set(self):
        """route_to should always be overwritten based on classification, not taken from LLM."""
        raw = '{"classification": "spam", "confidence": 0.99, "urgency": "low", "sender_type": "unknown", "route_to": "deep_analysis"}'
        result = _parse_classification(raw)
        # We override route_to based on classification, not trust the LLM
        assert result["route_to"] == "skip"


class TestDefaultClassification:
    def test_returns_safe_defaults(self):
        """Default should be newsletter/archive — never route unknown emails to deep analysis."""
        d = _default_classification()
        assert d["classification"] == "newsletter"
        assert d["route_to"] == "archive"
        assert d["urgency"] == "low"
        assert d["confidence"] == 0.0

    def test_returns_fresh_dict_each_time(self):
        """Make sure it returns a new dict, not a shared mutable reference."""
        d1 = _default_classification()
        d2 = _default_classification()
        d1["classification"] = "spam"
        assert d2["classification"] == "newsletter"


class TestPreClassify:
    """Test zero-cost heuristic pre-classification."""

    def test_noreply_sender_is_automated(self):
        email = make_email(raw_headers={"from": "noreply@amazon.com"})
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "automated"
        assert result["route_to"] == "regex_parse"

    def test_no_reply_with_dash(self):
        email = make_email(raw_headers={"from": "no-reply@github.com"})
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "automated"

    def test_notifications_sender(self):
        email = make_email(raw_headers={"from": "notifications@slack.com"})
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "automated"

    def test_list_unsubscribe_header(self):
        email = make_email(raw_headers={
            "from": "cool-person@startup.com",
            "List-Unsubscribe": "<mailto:unsub@startup.com>",
        })
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "newsletter"
        assert result["route_to"] == "archive"

    def test_precedence_bulk(self):
        email = make_email(raw_headers={
            "from": "team@company.com",
            "precedence": "bulk",
        })
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "newsletter"

    def test_bulk_sender_domain(self):
        email = make_email(raw_headers={"from": "bounce@mail.sendgrid.net"})
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "newsletter"

    def test_unsubscribe_in_body_tail(self):
        body = "Hey check out our product! " * 50 + "\nTo unsubscribe, manage your preferences here."
        email = make_email(raw_headers={"from": "promo@somecompany.io"}, full_body=body)
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "newsletter"

    def test_real_human_returns_none(self):
        """A genuine human email should NOT be pre-classified — let the LLM decide."""
        email = make_email(
            raw_headers={"from": "Keith Johnson <keith@example.com>"},
            full_body="Hey Nathan, just wanted to follow up on our conversation about the project.",
        )
        result = pre_classify(email)
        assert result is None

    def test_short_body_without_unsubscribe_returns_none(self):
        email = make_email(
            raw_headers={"from": "someone@company.com"},
            full_body="Can you send me the doc?",
        )
        result = pre_classify(email)
        assert result is None

    def test_info_at_sender(self):
        email = make_email(raw_headers={"from": "info@restaurant.com"})
        result = pre_classify(email)
        assert result is not None
        assert result["classification"] == "automated"
