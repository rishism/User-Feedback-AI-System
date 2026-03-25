"""CSV Agent — parses uploaded CSV files and stores feedback in SQLite."""

import json
import logging
import time

from src.db.database import init_db
from src.db.queries import insert_feedback, log_processing
from src.models.schemas import FeedbackItem
from src.models.state import FeedbackItemState, PipelineState
from src.observability.metrics import LatencyTimer, ProcessingMetric

logger = logging.getLogger(__name__)


def ingest_feedback_items(
    items: list[FeedbackItem],
    conn=None,
) -> list[FeedbackItemState]:
    """Store feedback items in the database and return state dicts for the pipeline."""
    init_db()
    state_items: list[FeedbackItemState] = []

    for item in items:
        feedback_id = insert_feedback(
            source_id=item.source_id,
            source_type=item.source_type,
            content_text=item.content_text,
            source_file=item.source_file,
            subject=item.subject,
            sender=item.sender,
            rating=item.rating,
            platform=item.platform,
            priority_hint=item.priority_hint,
            original_date=item.original_date,
            app_version=item.app_version,
            raw_json=item.raw_json,
            conn=conn,
        )

        state_items.append(
            FeedbackItemState(
                feedback_id=feedback_id,
                source_id=item.source_id,
                source_type=item.source_type,
                content_text=item.content_text,
                subject=item.subject,
                rating=item.rating,
                platform=item.platform,
                app_version=item.app_version,
                raw_json=item.raw_json or "",
            )
        )

        log_processing(
            agent_name="csv_agent",
            action="ingest",
            status="success",
            feedback_id=feedback_id,
            input_summary=f"source={item.source_type}, id={item.source_id}",
            output_summary=f"feedback_id={feedback_id}",
            conn=conn,
        )

    return state_items


def ingest_node(state: PipelineState) -> dict:
    """LangGraph node: pick the current item from the list at current_index."""
    idx = state["current_index"]
    items = state["feedback_items"]

    if idx >= len(items):
        return {
            "current_item": None,
            "current_agent": "ingest",
            "status": "done",
        }

    current = items[idx]
    logger.info(
        f"Ingesting item {idx + 1}/{state['total_items']}: "
        f"{current['source_type']} {current['source_id']}"
    )

    return {
        "current_item": current,
        "current_agent": "ingest",
        "status": "ingesting",
        "classification": None,
        "analysis": None,
        "ticket": None,
        "quality_review": None,
        "revision_count": 0,
    }
