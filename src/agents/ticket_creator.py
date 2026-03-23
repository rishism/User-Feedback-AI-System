"""Ticket Creator Agent — generates structured tickets and stores via MCP or direct DB."""

import json
import logging
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.db.queries import (
    generate_ticket_id,
    insert_ticket,
    log_processing,
    update_feedback_status,
)
from src.observability.metrics import LatencyTimer
from src.models.state import PipelineState

logger = logging.getLogger(__name__)

TICKET_CREATOR_SYSTEM_PROMPT = """You are a technical writer creating a structured support ticket from user feedback for a productivity app called TaskPro.

Given the original feedback, its classification, and any analysis details, create a well-structured ticket.

Requirements:
- Title: Clear, actionable, under 80 characters. Format: "[Category] Brief description"
- Description: Structured with clear sections. Include:
  * Summary (1-2 sentences)
  * For Bugs: Steps to Reproduce, Expected Behavior, Actual Behavior, Environment
  * For Feature Requests: User Need, Proposed Solution, Impact Assessment
  * For Praise: Key Positive Points, Areas Highlighted
  * For Complaints: Issue Description, User Impact, Suggested Resolution
  * For Spam: Reason for Classification
- Priority: Based on severity (bugs) or impact (features) or Low (praise/spam)

You MUST respond with valid JSON only, no other text:
{
    "title": "...",
    "description": "...",
    "priority": "Critical|High|Medium|Low"
}"""


def _build_ticket_prompt(state: PipelineState) -> str:
    """Build the user message with all context for ticket generation."""
    item = state["current_item"]
    classification = state["classification"]
    analysis = state.get("analysis")

    parts = [
        f"Original Feedback: {item['content_text']}",
        f"Classification: {classification['category']} (confidence: {classification['confidence']})",
        f"Reasoning: {classification['reasoning']}",
    ]

    if item.get("rating") is not None:
        parts.append(f"Rating: {item['rating']}/5")
    if item.get("platform"):
        parts.append(f"Platform: {item['platform']}")

    if analysis:
        if analysis.get("technical_details"):
            parts.append(f"Bug Analysis: {json.dumps(analysis['technical_details'])}")
        if analysis.get("feature_details"):
            parts.append(f"Feature Analysis: {json.dumps(analysis['feature_details'])}")
        if analysis.get("suggested_title"):
            parts.append(f"Suggested Title: {analysis['suggested_title']}")
        if analysis.get("suggested_priority"):
            parts.append(f"Suggested Priority: {analysis['suggested_priority']}")

    # If this is a revision, include quality critic feedback
    review = state.get("quality_review")
    if review and not review.get("approved"):
        parts.append(f"\nQUALITY REVIEW FEEDBACK (revision needed):")
        parts.append(f"Score: {review['score']}/10")
        parts.append(f"Notes: {review['notes']}")
        suggestions = review.get("revision_suggestions", [])
        if suggestions:
            parts.append(f"Suggestions: {', '.join(suggestions)}")

    return "\n".join(parts)


def create_ticket_node(llm: ChatOpenAI, use_mcp: bool = False):
    """Create a ticket creator node function.

    Args:
        llm: The ChatOpenAI instance for generating ticket content.
        use_mcp: If True, create tickets via MCP server. If False, use direct DB insert.
    """

    def ticket_create_node(state: PipelineState) -> dict:
        """LangGraph node: create a ticket from classified/analyzed feedback."""
        item = state["current_item"]
        classification = state["classification"]
        analysis = state.get("analysis")

        logger.info(f"Creating ticket for feedback {item['source_id']}")

        user_msg = _build_ticket_prompt(state)

        with LatencyTimer() as timer:
            response = llm.invoke([
                SystemMessage(content=TICKET_CREATOR_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error(f"Ticket creator returned invalid JSON: {response.content}")
            result = {
                "title": f"[{classification['category']}] {item['content_text'][:60]}",
                "description": item["content_text"],
                "priority": analysis.get("suggested_priority", "Medium") if analysis else "Medium",
            }

        # Generate ticket ID and store
        ticket_id = generate_ticket_id()

        # Prepare technical/feature details as JSON strings
        tech_details = None
        feat_details = None
        actions = None
        if analysis:
            if analysis.get("technical_details"):
                tech_details = json.dumps(analysis["technical_details"])
            if analysis.get("feature_details"):
                feat_details = json.dumps(analysis["feature_details"])
            if analysis.get("suggested_actions"):
                actions = json.dumps(analysis["suggested_actions"])

        if use_mcp:
            ticket_id = _create_via_mcp(
                feedback_id=item["feedback_id"],
                category=classification["category"],
                confidence=classification["confidence"],
                title=result["title"],
                description=result["description"],
                priority=result["priority"],
                severity=analysis.get("technical_details", {}).get("severity") if analysis and analysis.get("technical_details") else None,
                technical_details=tech_details,
                feature_details=feat_details,
                suggested_actions=actions,
            )
        else:
            insert_ticket(
                ticket_id=ticket_id,
                feedback_id=item["feedback_id"],
                category=classification["category"],
                confidence=classification["confidence"],
                title=result["title"],
                description=result["description"],
                priority=result["priority"],
                severity=analysis.get("technical_details", {}).get("severity") if analysis and analysis.get("technical_details") else None,
                technical_details=tech_details,
                feature_details=feat_details,
                suggested_actions=actions,
            )

        ticket_data = {
            "ticket_id": ticket_id,
            "feedback_id": item["feedback_id"],
            "category": classification["category"],
            "confidence": classification["confidence"],
            "title": result["title"],
            "description": result["description"],
            "priority": result["priority"],
        }

        update_feedback_status(item["feedback_id"], "ticketed")
        log_processing(
            agent_name="ticket_creator",
            action="create_ticket",
            status="success",
            feedback_id=item["feedback_id"],
            ticket_id=ticket_id,
            input_summary=f"category={classification['category']}",
            output_summary=f"ticket_id={ticket_id}, title={result['title'][:50]}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        logger.info(f"Created ticket {ticket_id}: {result['title']}")

        return {
            "ticket": ticket_data,
            "current_agent": "ticket_creator",
            "status": "ticketing",
        }

    return ticket_create_node


def _create_via_mcp(**kwargs) -> str:
    """Create a ticket via the MCP server (stdio transport)."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from fastmcp import Client

    server_path = str(
        Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
    )

    async def _call():
        async with Client(server_path) as client:
            result = await client.call_tool("create_ticket", kwargs)
            if result:
                data = json.loads(result[0].text if hasattr(result[0], 'text') else str(result[0]))
                return data.get("ticket_id", "UNKNOWN")
            return "UNKNOWN"

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, _call()).result()
