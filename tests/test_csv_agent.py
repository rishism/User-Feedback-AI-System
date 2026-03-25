"""Tests for CSV parsing and the CSV agent."""

import pytest

from src.utils.csv_parser import (
    detect_csv_type,
    parse_app_store_reviews,
    parse_csv_file,
    parse_support_emails,
)

SAMPLE_REVIEWS_CSV = """review_id,platform,rating,review_text,user_name,date,app_version
R001,Google Play,1,"App crashes on settings page",john_doe,2026-03-15,3.2.1
R002,App Store,5,"Love this app!",sarah_k,2026-03-14,3.2.0
"""

SAMPLE_EMAILS_CSV = """email_id,subject,body,sender_email,timestamp,priority
E001,App Crash Report,"The app crashes on my iPad",user@email.com,2026-03-15T09:30:00,High
E002,Feature Request: Dark Mode,"Please add dark mode",user2@email.com,2026-03-14T14:00:00,Medium
"""


class TestDetectCsvType:
    def test_detect_reviews(self):
        assert detect_csv_type(SAMPLE_REVIEWS_CSV) == "app_store_review"

    def test_detect_emails(self):
        assert detect_csv_type(SAMPLE_EMAILS_CSV) == "support_email"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Cannot detect CSV type"):
            detect_csv_type("col1,col2\na,b\n")


class TestParseAppStoreReviews:
    def test_parse_basic(self):
        items = parse_app_store_reviews(SAMPLE_REVIEWS_CSV)
        assert len(items) == 2
        assert items[0].source_id == "R001"
        assert items[0].source_type == "app_store_review"
        assert items[0].rating == 1
        assert items[0].platform == "Google Play"
        assert "crashes" in items[0].content_text

    def test_parse_preserves_rating(self):
        items = parse_app_store_reviews(SAMPLE_REVIEWS_CSV)
        assert items[1].rating == 5


class TestParseSupportEmails:
    def test_parse_basic(self):
        items = parse_support_emails(SAMPLE_EMAILS_CSV)
        assert len(items) == 2
        assert items[0].source_id == "E001"
        assert items[0].source_type == "support_email"
        assert items[0].subject == "App Crash Report"
        assert items[0].priority_hint == "High"

    def test_parse_content_is_body(self):
        items = parse_support_emails(SAMPLE_EMAILS_CSV)
        assert "crashes" in items[0].content_text


class TestParseCsvFile:
    def test_dispatch_reviews(self):
        items = parse_csv_file(SAMPLE_REVIEWS_CSV, "app_store_review")
        assert len(items) == 2

    def test_dispatch_emails(self):
        items = parse_csv_file(SAMPLE_EMAILS_CSV, "support_email")
        assert len(items) == 2

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            parse_csv_file(SAMPLE_REVIEWS_CSV, "unknown_type")
