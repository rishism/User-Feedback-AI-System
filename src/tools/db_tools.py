"""LangChain @tool wrappers around src/db/queries.py for agentic tool-calling.

These give ReAct agents the ability to look up feedback, search tickets,
and inspect processing history autonomously.
"""

import json
from typing import Optional

from langchain_core.tools import tool

from src.db.queries import (
    get_feedback_by_id,
    get_processing_logs,
    get_ticket_by_id,
    get_tickets,
)


@tool
def read_feedback(feedback_id: int) -> str:
    """Look up the original raw feedback record by its database ID.

    Use this when you need the full original feedback text, sender info,
    rating, platform, or other metadata for a given feedback_id.

    Args:
        feedback_id: The raw_feedback table ID.

    Returns:
        JSON string of the feedback record, or an error message.
    """
    row = get_feedback_by_id(feedback_id)
    if row is None:
        return json.dumps({"error": f"No feedback found with id={feedback_id}"})
    return json.dumps(row, default=str)


@tool
def search_similar_tickets(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Search existing tickets by category and/or priority.

    Use this to check for duplicate tickets, see how similar feedback
    was handled before, or assess consistency of prioritization.

    Args:
        category: Filter by category — Bug, Feature Request, Praise, Complaint, Spam.
        priority: Filter by priority — Critical, High, Medium, Low.
        limit: Max tickets to return (default 5).

    Returns:
        JSON array of matching ticket records.
    """
    tickets = get_tickets(category=category, priority=priority, limit=limit)
    return json.dumps(tickets, default=str)


@tool
def get_ticket_details(ticket_id: str) -> str:
    """Fetch a single ticket by its ticket_id (e.g., 'TKT-20260324-001').

    Use this to review a specific ticket's title, description, priority,
    quality score, and other fields.

    Args:
        ticket_id: The ticket ID string.

    Returns:
        JSON string of the ticket record, or an error message.
    """
    row = get_ticket_by_id(ticket_id)
    if row is None:
        return json.dumps({"error": f"No ticket found with id={ticket_id}"})
    return json.dumps(row, default=str)


@tool
def get_processing_history(feedback_id: int) -> str:
    """Retrieve the processing log for a feedback item.

    Shows which agents processed this feedback, what actions they took,
    and the results. Useful for understanding what has already been done.

    Args:
        feedback_id: The raw_feedback table ID.

    Returns:
        JSON array of processing log entries.
    """
    logs = get_processing_logs(feedback_id=feedback_id)
    return json.dumps(logs, default=str)


# Convenience list for agents that need all DB tools
ALL_DB_TOOLS = [read_feedback, search_similar_tickets, get_ticket_details, get_processing_history]
