"""CSV parsing utilities for feedback ingestion."""

import csv
import io
import json
from typing import BinaryIO

from src.models.schemas import FeedbackItem


def parse_app_store_reviews(
    file_content: str,
    source_file: str = "upload",
) -> list[FeedbackItem]:
    """Parse an app store reviews CSV into FeedbackItem list."""
    reader = csv.DictReader(io.StringIO(file_content))
    items = []
    for row in reader:
        items.append(
            FeedbackItem(
                source_id=row.get("review_id", ""),
                source_type="app_store_review",
                content_text=row.get("review_text", ""),
                sender=row.get("user_name"),
                rating=int(row["rating"]) if row.get("rating") else None,
                platform=row.get("platform"),
                original_date=row.get("date"),
                app_version=row.get("app_version"),
                source_file=source_file,
                raw_json=json.dumps(row),
            )
        )
    return items


def parse_support_emails(
    file_content: str,
    source_file: str = "upload",
) -> list[FeedbackItem]:
    """Parse a support emails CSV into FeedbackItem list."""
    reader = csv.DictReader(io.StringIO(file_content))
    items = []
    for row in reader:
        items.append(
            FeedbackItem(
                source_id=row.get("email_id", ""),
                source_type="support_email",
                content_text=row.get("body", ""),
                subject=row.get("subject"),
                sender=row.get("sender_email"),
                priority_hint=row.get("priority") or None,
                original_date=row.get("timestamp"),
                source_file=source_file,
                raw_json=json.dumps(row),
            )
        )
    return items


def parse_csv_file(
    file_content: str,
    source_type: str,
    source_file: str = "upload",
) -> list[FeedbackItem]:
    """Parse a CSV file based on source type."""
    if source_type == "app_store_review":
        return parse_app_store_reviews(file_content, source_file)
    elif source_type == "support_email":
        return parse_support_emails(file_content, source_file)
    else:
        raise ValueError(f"Unknown source type: {source_type}")


def detect_csv_type(file_content: str) -> str:
    """Auto-detect whether a CSV is app store reviews or support emails."""
    reader = csv.DictReader(io.StringIO(file_content))
    headers = set(reader.fieldnames or [])
    if "review_id" in headers or "review_text" in headers:
        return "app_store_review"
    elif "email_id" in headers or "body" in headers:
        return "support_email"
    raise ValueError(
        f"Cannot detect CSV type from headers: {headers}. "
        "Expected 'review_id'/'review_text' for reviews or 'email_id'/'body' for emails."
    )
