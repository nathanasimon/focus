"""Tests for regex parser — false positives and missed matches are the main risk."""

from tests.conftest import make_email
from src.processing.regex_parser import parse_automated_email, _detect_category, _clean_amount


class TestOrderNumbers:
    def test_basic_order_number(self):
        email = make_email(subject="Your order #12345678", full_body="Thank you for your purchase.")
        result = parse_automated_email(email)
        assert "12345678" in result["order_numbers"]

    def test_order_with_dashes(self):
        email = make_email(subject="Order confirmation", full_body="Order number: 111-2345678-9012345")
        result = parse_automated_email(email)
        assert any("111-2345678-9012345" in o for o in result["order_numbers"])

    def test_confirmation_number(self):
        email = make_email(subject="Booking confirmed", full_body="Confirmation #ABC12345")
        result = parse_automated_email(email)
        assert "ABC12345" in result["order_numbers"]


class TestTrackingNumbers:
    def test_ups_tracking(self):
        email = make_email(full_body="Your UPS tracking number is 1Z999AA10123456784")
        result = parse_automated_email(email)
        assert "1Z999AA10123456784" in result["tracking_numbers"]

    def test_usps_tracking(self):
        email = make_email(full_body="USPS tracking: 9400111899223100002033")
        result = parse_automated_email(email)
        assert "9400111899223100002033" in result["tracking_numbers"]

    def test_bare_12_digit_number_not_matched_without_context(self):
        """The fix: bare 12-digit numbers should NOT match as FedEx without tracking context."""
        email = make_email(full_body="Your account balance is 123456789012 as of today.")
        result = parse_automated_email(email)
        # Should NOT be in tracking numbers — it's just a random 12-digit number
        assert "123456789012" not in result["tracking_numbers"]

    def test_fedex_with_context(self):
        email = make_email(full_body="FedEx tracking number: 123456789012")
        result = parse_automated_email(email)
        assert "123456789012" in result["tracking_numbers"]

    def test_generic_tracking_number(self):
        email = make_email(full_body="Tracking #: ABCDEF1234567890")
        result = parse_automated_email(email)
        assert "ABCDEF1234567890" in result["tracking_numbers"]


class TestAmounts:
    def test_basic_amount(self):
        email = make_email(full_body="Total: $49.99")
        result = parse_automated_email(email)
        assert 49.99 in result["amounts"]

    def test_amount_with_commas(self):
        email = make_email(full_body="You were charged $1,234.56")
        result = parse_automated_email(email)
        assert 1234.56 in result["amounts"]

    def test_amount_no_cents(self):
        email = make_email(full_body="Amount: $500")
        result = parse_automated_email(email)
        assert 500.0 in result["amounts"]

    def test_multiple_amounts(self):
        email = make_email(full_body="Subtotal: $100.00\nTax: $8.50\nTotal: $108.50")
        result = parse_automated_email(email)
        assert len(result["amounts"]) >= 2


class TestCarriersAndStatuses:
    def test_detect_ups(self):
        email = make_email(full_body="Shipped via UPS Ground")
        result = parse_automated_email(email)
        assert "Ups" in result["carriers"]

    def test_detect_shipped_status(self):
        email = make_email(full_body="Your order has shipped!")
        result = parse_automated_email(email)
        assert "shipped" in result["statuses"]

    def test_detect_delivered(self):
        email = make_email(full_body="Your package was delivered at 2:30 PM")
        result = parse_automated_email(email)
        assert "delivered" in result["statuses"]

    def test_detect_in_transit(self):
        email = make_email(full_body="Your package is in transit")
        result = parse_automated_email(email)
        assert "in transit" in result["statuses"]


class TestCategoryDetection:
    def test_order_category(self):
        email = make_email(subject="Your order confirmation")
        assert _detect_category(email) == "order"

    def test_shipping_category(self):
        email = make_email(subject="Your package has shipped!")
        assert _detect_category(email) == "shipping"

    def test_billing_category(self):
        email = make_email(subject="Your payment of $50.00 is due")
        assert _detect_category(email) == "billing"

    def test_alert_category(self):
        email = make_email(subject="Security alert: new login detected")
        assert _detect_category(email) == "alert"

    def test_subscription_category(self):
        email = make_email(subject="Your subscription renewal")
        assert _detect_category(email) == "subscription"

    def test_unknown_category(self):
        email = make_email(subject="Hello there", raw_headers={"from": "friend@example.com"})
        assert _detect_category(email) == "other"


class TestCleanAmount:
    def test_simple(self):
        assert _clean_amount("49.99") == 49.99

    def test_commas(self):
        assert _clean_amount("1,234.56") == 1234.56

    def test_no_cents(self):
        assert _clean_amount("500") == 500.0

    def test_invalid_returns_zero(self):
        assert _clean_amount("abc") == 0.0

    def test_empty_returns_zero(self):
        assert _clean_amount("") == 0.0
