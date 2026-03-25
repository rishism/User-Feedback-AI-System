"""Tests for the Quality Critic agent."""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from src.agents.quality_critic import create_quality_review_node


def _make_review_state(revision_count=0):
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
        "analysis": None,
        "ticket": {
            "ticket_id": "TKT-20260323-001",
            "feedback_id": 1,
            "category": "Bug",
            "confidence": 0.95,
            "title": "[Bug] Settings crash",
            "description": "The app crashes when opening settings page.",
            "priority": "High",
        },
        "quality_review": None,
        "current_agent": "ticket_creator",
        "status": "ticketing",
        "error_message": None,
        "revision_count": revision_count,
        "completed_tickets": [],
    }


class TestQualityCritic:
    @patch("src.agents.quality_critic.create_agent")
    def test_approves_good_ticket(self, mock_create_agent):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [
                AIMessage(content=json.dumps({
                    "score": 8.5,
                    "breakdown": {
                        "title_clarity": 2,
                        "description_completeness": 2.5,
                        "priority_accuracy": 2,
                        "technical_accuracy": 1.5,
                        "actionability": 0.5,
                    },
                    "approved": True,
                    "notes": "Good ticket with clear details.",
                    "revision_suggestions": [],
                }))
            ]
        }
        mock_create_agent.return_value = mock_agent

        review = create_quality_review_node(MagicMock())
        result = review(_make_review_state())

        assert result["quality_review"]["approved"] is True
        assert result["quality_review"]["score"] == 8.5
        assert result["revision_count"] == 0

    @patch("src.agents.quality_critic.create_agent")
    def test_rejects_poor_ticket(self, mock_create_agent):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [
                AIMessage(content=json.dumps({
                    "score": 5.0,
                    "breakdown": {},
                    "approved": False,
                    "notes": "Missing reproduction steps.",
                    "revision_suggestions": ["Add steps to reproduce"],
                }))
            ]
        }
        mock_create_agent.return_value = mock_agent

        review = create_quality_review_node(MagicMock())
        result = review(_make_review_state())

        assert result["quality_review"]["approved"] is False
        assert result["revision_count"] == 1

    @patch("src.agents.quality_critic.create_agent")
    def test_handles_invalid_json(self, mock_create_agent):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [AIMessage(content="not json")]
        }
        mock_create_agent.return_value = mock_agent

        review = create_quality_review_node(MagicMock())
        result = review(_make_review_state())

        # Auto-approves on parse error
        assert result["quality_review"]["approved"] is True
        assert result["quality_review"]["score"] == 7.0
