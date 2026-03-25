"""Tests for the Feedback Classifier agent."""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.agents.classifier import create_classify_node


def _make_state(content_text="App crashes", rating=1, source_id="R001"):
    """Create a minimal PipelineState dict for testing."""
    return {
        "batch_id": "test-batch",
        "trace_id": "test-trace",
        "feedback_items": [],
        "current_index": 0,
        "total_items": 1,
        "current_item": {
            "feedback_id": 1,
            "source_id": source_id,
            "source_type": "app_store_review",
            "content_text": content_text,
            "subject": None,
            "rating": rating,
            "platform": "Google Play",
            "app_version": "3.2.1",
            "raw_json": "{}",
        },
        "classification": None,
        "analysis": None,
        "ticket": None,
        "quality_review": None,
        "current_agent": "",
        "status": "ingesting",
        "error_message": None,
        "revision_count": 0,
        "completed_tickets": [],
    }


class TestClassifier:
    @patch("src.agents.classifier.update_feedback_status")
    @patch("src.agents.classifier.log_processing")
    @patch("src.agents.classifier.create_agent")
    def test_classify_bug(self, mock_create_agent, mock_log, mock_status):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [
                AIMessage(content=json.dumps({
                    "category": "Bug",
                    "confidence": 0.95,
                    "reasoning": "User reports app crash",
                }))
            ]
        }
        mock_create_agent.return_value = mock_agent

        classify = create_classify_node(MagicMock())
        result = classify(_make_state("App crashes on settings page"))

        assert result["classification"]["category"] == "Bug"
        assert result["classification"]["confidence"] == 0.95
        assert result["current_agent"] == "classifier"

    @patch("src.agents.classifier.update_feedback_status")
    @patch("src.agents.classifier.log_processing")
    @patch("src.agents.classifier.create_agent")
    def test_classify_feature_request(self, mock_create_agent, mock_log, mock_status):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [
                AIMessage(content=json.dumps({
                    "category": "Feature Request",
                    "confidence": 0.88,
                    "reasoning": "User requesting dark mode",
                }))
            ]
        }
        mock_create_agent.return_value = mock_agent

        classify = create_classify_node(MagicMock())
        result = classify(_make_state("Please add dark mode", rating=4))

        assert result["classification"]["category"] == "Feature Request"

    @patch("src.agents.classifier.update_feedback_status")
    @patch("src.agents.classifier.log_processing")
    @patch("src.agents.classifier.create_agent")
    def test_handles_invalid_json(self, mock_create_agent, mock_log, mock_status):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [AIMessage(content="not valid json")]
        }
        mock_create_agent.return_value = mock_agent

        classify = create_classify_node(MagicMock())
        result = classify(_make_state())

        # Should fall back to Complaint with 0.5 confidence
        assert result["classification"]["category"] == "Complaint"
        assert result["classification"]["confidence"] == 0.5
