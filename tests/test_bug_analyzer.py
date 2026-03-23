"""Tests for the Bug Analyzer agent."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.bug_analyzer import create_bug_analyze_node

_db_patches = [
    patch("src.agents.bug_analyzer.update_feedback_status"),
    patch("src.agents.bug_analyzer.log_processing"),
]


@pytest.fixture(autouse=True)
def mock_db():
    mocks = [p.start() for p in _db_patches]
    yield mocks
    for p in _db_patches:
        p.stop()


def _make_bug_state():
    return {
        "batch_id": "test",
        "trace_id": "test-trace",
        "feedback_items": [],
        "current_index": 0,
        "total_items": 1,
        "current_item": {
            "feedback_id": 1,
            "source_id": "R001",
            "source_type": "app_store_review",
            "content_text": "App crashes when I open settings. Pixel 7, Android 14.",
            "subject": None,
            "rating": 1,
            "platform": "Google Play",
            "app_version": "3.2.1",
            "raw_json": "{}",
        },
        "classification": {"category": "Bug", "confidence": 0.95, "reasoning": "crash report"},
        "analysis": None,
        "ticket": None,
        "quality_review": None,
        "current_agent": "classifier",
        "status": "classifying",
        "error_message": None,
        "revision_count": 0,
        "completed_tickets": [],
    }


class TestBugAnalyzer:
    def test_extracts_technical_details(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "severity": "Major",
                "affected_component": "Settings",
                "platform_details": {"device": "Pixel 7", "os": "Android 14", "app_version": "3.2.1"},
                "steps_to_reproduce": ["Open app", "Navigate to settings"],
                "expected_behavior": "Settings page loads",
                "actual_behavior": "App crashes",
                "suggested_title": "Settings page crash on Pixel 7",
                "suggested_priority": "High",
                "suggested_actions": ["Reproduce on Pixel 7", "Check crash logs"],
            })
        )

        analyze = create_bug_analyze_node(mock_llm)
        result = analyze(_make_bug_state())

        assert result["analysis"]["technical_details"]["severity"] == "Major"
        assert result["analysis"]["technical_details"]["affected_component"] == "Settings"
        assert result["analysis"]["feature_details"] is None
        assert result["current_agent"] == "bug_analyzer"

    def test_handles_invalid_json(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="broken json")

        analyze = create_bug_analyze_node(mock_llm)
        result = analyze(_make_bug_state())

        # Should fall back to reasonable defaults
        assert result["analysis"]["technical_details"]["severity"] == "Major"
        assert result["analysis"]["suggested_priority"] == "Medium"
