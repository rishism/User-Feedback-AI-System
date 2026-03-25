"""Tests for the LangGraph workflow routing logic."""

from src.graph.workflow import (
    route_from_supervisor,
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
        "messages": [],
        "next_agent": "",
        "supervisor_reasoning": "",
    }
    base.update(overrides)
    return base


class TestRouteFromSupervisor:
    """Tests for the supervisor routing edge function."""

    def test_routes_to_bug_analyzer(self):
        state = _make_state(next_agent="bug_analyzer")
        assert route_from_supervisor(state) == "bug_analyzer"

    def test_routes_to_feature_extractor(self):
        state = _make_state(next_agent="feature_extractor")
        assert route_from_supervisor(state) == "feature_extractor"

    def test_routes_to_ticket_creator(self):
        state = _make_state(next_agent="ticket_creator")
        assert route_from_supervisor(state) == "ticket_creator"

    def test_routes_to_finalize(self):
        state = _make_state(next_agent="finalize")
        assert route_from_supervisor(state) == "finalize"


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
