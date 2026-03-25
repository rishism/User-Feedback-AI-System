"""Tests for the Ticket Creator agent."""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage

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
    @patch("src.agents.ticket_creator.create_agent")
    def test_creates_ticket(self, mock_create_agent):
        # Simulate a ReAct agent that calls create_ticket tool and gets a result
        tool_call_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "create_ticket",
                "id": "call_1",
                "args": {
                    "feedback_id": 1,
                    "category": "Bug",
                    "confidence": 0.95,
                    "title": "[Bug] Settings page crash on Android",
                    "description": "The app crashes when opening settings.",
                    "priority": "High",
                },
            }],
        )
        tool_result_msg = ToolMessage(
            content=json.dumps({"ticket_id": "TKT-20260323-001", "status": "created"}),
            name="create_ticket",
            tool_call_id="call_1",
        )
        final_msg = AIMessage(content="Created ticket TKT-20260323-001.")

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [tool_call_msg, tool_result_msg, final_msg]
        }
        mock_create_agent.return_value = mock_agent

        create_ticket = create_ticket_node(MagicMock())
        result = create_ticket(_make_ticket_state())

        assert result["ticket"]["ticket_id"] == "TKT-20260323-001"
        assert result["ticket"]["title"] == "[Bug] Settings page crash on Android"
        assert result["current_agent"] == "ticket_creator"

    @patch("src.agents.ticket_creator.create_agent")
    def test_handles_agent_error(self, mock_create_agent):
        # Simulate agent raising an exception
        mock_agent = MagicMock()
        mock_agent.invoke.side_effect = RuntimeError("Agent failed")
        mock_create_agent.return_value = mock_agent

        create_ticket = create_ticket_node(MagicMock())
        result = create_ticket(_make_ticket_state())

        # Should fall back to default ticket
        assert result["ticket"]["ticket_id"] == "UNKNOWN"
        assert "[Bug]" in result["ticket"]["title"]
        assert result["ticket"]["priority"] == "Medium"
