"""Tests for the LangGraph workflow routing logic."""

from src.graph.workflow import (
    route_after_classification,
    route_after_review,
    route_next_or_end,
)


def _make_state(**overrides):
    base = {
        "batch_id": "test",
        "trace_id": "test-trace",
        "feedback_items": [{}],
        "current_index": 0,
        "total_items": 1,
        "current_item": None,
        "classification": None,
        "analysis": None,
        "ticket": None,
        "quality_review": None,
        "current_agent": "",
        "status": "",
        "error_message": None,
        "revision_count": 0,
        "completed_tickets": [],
    }
    base.update(overrides)
    return base


class TestRouteAfterClassification:
    def test_routes_bug(self):
        state = _make_state(
            classification={"category": "Bug", "confidence": 0.9, "reasoning": ""}
        )
        assert route_after_classification(state) == "bug_analyze"

    def test_routes_feature_request(self):
        state = _make_state(
            classification={"category": "Feature Request", "confidence": 0.9, "reasoning": ""}
        )
        assert route_after_classification(state) == "feature_extract"

    def test_routes_praise_to_ticket(self):
        state = _make_state(
            classification={"category": "Praise", "confidence": 0.9, "reasoning": ""}
        )
        assert route_after_classification(state) == "create_ticket"

    def test_routes_complaint_to_ticket(self):
        state = _make_state(
            classification={"category": "Complaint", "confidence": 0.9, "reasoning": ""}
        )
        assert route_after_classification(state) == "create_ticket"

    def test_routes_spam_to_ticket(self):
        state = _make_state(
            classification={"category": "Spam", "confidence": 0.9, "reasoning": ""}
        )
        assert route_after_classification(state) == "create_ticket"


class TestRouteAfterReview:
    def test_approved_goes_to_finalize(self):
        state = _make_state(
            quality_review={"approved": True, "score": 8.5, "notes": ""},
            revision_count=0,
        )
        assert route_after_review(state) == "finalize"

    def test_rejected_goes_to_create_ticket(self):
        state = _make_state(
            quality_review={"approved": False, "score": 5.0, "notes": ""},
            revision_count=0,
        )
        assert route_after_review(state) == "create_ticket"

    def test_max_revisions_forces_finalize(self):
        state = _make_state(
            quality_review={"approved": False, "score": 5.0, "notes": ""},
            revision_count=2,  # At max
        )
        assert route_after_review(state) == "finalize"


class TestRouteNextOrEnd:
    def test_more_items_goes_to_ingest(self):
        state = _make_state(current_index=0, total_items=3)
        assert route_next_or_end(state) == "ingest"

    def test_no_more_items_goes_to_end(self):
        state = _make_state(current_index=3, total_items=3)
        assert route_next_or_end(state) == "end"

    def test_last_item_goes_to_end(self):
        state = _make_state(current_index=1, total_items=1)
        assert route_next_or_end(state) == "end"
