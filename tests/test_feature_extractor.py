"""Tests for the Feature Extractor agent."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.feature_extractor import create_feature_extract_node

_db_patches = [
    patch("src.agents.feature_extractor.update_feedback_status"),
    patch("src.agents.feature_extractor.log_processing"),
]


@pytest.fixture(autouse=True)
def mock_db():
    mocks = [p.start() for p in _db_patches]
    yield mocks
    for p in _db_patches:
        p.stop()


def _make_feature_state():
    return {
        "batch_id": "test",
        "trace_id": "test-trace",
        "feedback_items": [],
        "current_index": 0,
        "total_items": 1,
        "current_item": {
            "feedback_id": 2,
            "source_id": "R004",
            "source_type": "app_store_review",
            "content_text": "Would love to see dark mode. My eyes hurt at night.",
            "subject": None,
            "rating": 4,
            "platform": "App Store",
            "app_version": "3.2.0",
            "raw_json": "{}",
        },
        "classification": {"category": "Feature Request", "confidence": 0.92, "reasoning": "dark mode request"},
        "analysis": None,
        "ticket": None,
        "quality_review": None,
        "current_agent": "classifier",
        "status": "classifying",
        "error_message": None,
        "revision_count": 0,
        "completed_tickets": [],
    }


class TestFeatureExtractor:
    def test_extracts_feature_details(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "feature_name": "Dark Mode",
                "description": "User wants a dark color theme to reduce eye strain at night.",
                "user_impact": "High",
                "demand_signal": "Strong",
                "existing_alternatives": "None in-app",
                "suggested_title": "Add dark mode option",
                "suggested_priority": "Medium",
                "suggested_actions": ["Design dark theme", "Add toggle in settings"],
            })
        )

        extract = create_feature_extract_node(mock_llm)
        result = extract(_make_feature_state())

        assert result["analysis"]["feature_details"]["feature_name"] == "Dark Mode"
        assert result["analysis"]["technical_details"] is None
        assert result["current_agent"] == "feature_extractor"

    def test_handles_invalid_json(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not json")

        extract = create_feature_extract_node(mock_llm)
        result = extract(_make_feature_state())

        assert result["analysis"]["feature_details"]["feature_name"] == "Unknown Feature"
