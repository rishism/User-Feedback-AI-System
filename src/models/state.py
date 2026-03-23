"""LangGraph pipeline state definition."""

import operator
from typing import Annotated, Optional, TypedDict


class FeedbackItemState(TypedDict):
    """State for a single feedback item flowing through the pipeline."""

    feedback_id: int  # raw_feedback.id
    source_id: str
    source_type: str
    content_text: str
    subject: Optional[str]
    rating: Optional[int]
    platform: Optional[str]
    app_version: Optional[str]
    raw_json: str


class PipelineState(TypedDict):
    """Top-level LangGraph state shared across all nodes."""

    # Batch-level
    batch_id: str
    trace_id: str
    feedback_items: list[FeedbackItemState]
    current_index: int
    total_items: int

    # Current item being processed
    current_item: Optional[FeedbackItemState]

    # Classification output
    classification: Optional[dict]  # category, confidence, reasoning

    # Analysis output (bug or feature details)
    analysis: Optional[dict]

    # Generated ticket
    ticket: Optional[dict]

    # Quality review result
    quality_review: Optional[dict]  # score, approved, notes

    # Control flow
    current_agent: str  # for real-time UI status updates
    status: str  # ingesting | classifying | analyzing | ticketing | reviewing | done | error
    error_message: Optional[str]
    revision_count: int

    # Accumulator for completed tickets
    completed_tickets: Annotated[list[str], operator.add]  # ticket_ids
