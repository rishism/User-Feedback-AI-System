"""Tests for the Ticket Creator agent."""

import json
from unittest.mock import MagicMock, patch

from src.agents.ticket_creator import create_ticket_node


def _make_ticket_state():
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
            "content_text": "App crashes on settings",
            "subject": None,
            "rating": 1,
            "platform": "Google Play",
            "app_version": "3.2.1",
            "raw_json": "{}",
        },
        "classification": {
            "category": "Bug",
            "confidence": 0.95,
            "reasoning": "crash report",
        },
        "analysis": {
            "technical_details": {"severity": "Major", "affected_component": "Settings"},
            "feature_details": None,
            "suggested_title": "Settings crash",
            "suggested_priority": "High",
            "suggested_actions": ["Investigate"],
        },
        "ticket": None,
        "quality_review": None,
        "current_agent": "bug_analyzer",
        "status": "analyzing",
        "error_message": None,
        "revision_count": 0,
        "completed_tickets": [],
    }


class TestTicketCreator:
    @patch("src.agents.ticket_creator.insert_ticket")
    @patch("src.agents.ticket_creator.generate_ticket_id", return_value="TKT-20260323-001")
    @patch("src.agents.ticket_creator.update_feedback_status")
    @patch("src.agents.ticket_creator.log_processing")
    def test_creates_ticket(self, mock_log, mock_status, mock_gen_id, mock_insert):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content=json.dumps({
                "title": "[Bug] Settings page crash on Android",
                "description": "The app crashes when opening settings.",
                "priority": "High",
            })
        )

        create_ticket = create_ticket_node(mock_llm, use_mcp=False)
        result = create_ticket(_make_ticket_state())

        assert result["ticket"]["ticket_id"] == "TKT-20260323-001"
        assert result["ticket"]["title"] == "[Bug] Settings page crash on Android"
        assert result["current_agent"] == "ticket_creator"
        mock_insert.assert_called_once()

    @patch("src.agents.ticket_creator.insert_ticket")
    @patch("src.agents.ticket_creator.generate_ticket_id", return_value="TKT-20260323-002")
    @patch("src.agents.ticket_creator.update_feedback_status")
    @patch("src.agents.ticket_creator.log_processing")
    def test_handles_invalid_json(self, mock_log, mock_status, mock_gen_id, mock_insert):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not json")

        create_ticket = create_ticket_node(mock_llm, use_mcp=False)
        result = create_ticket(_make_ticket_state())

        # Should fall back to default ticket
        assert result["ticket"]["ticket_id"] == "TKT-20260323-002"
        assert "[Bug]" in result["ticket"]["title"]
