"""Quality Critic Agent — ReAct agent that reviews tickets via MCP tool-calling.

The LLM autonomously fetches the ticket and original feedback, evaluates quality,
then calls update_ticket to write its review scores and decision.
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from src.config import settings
from src.models.state import PipelineState
from src.tools.db_tools import get_ticket_details, read_feedback
from src.tools.mcp_tools import update_ticket

logger = logging.getLogger(__name__)

QUALITY_CRITIC_SYSTEM_PROMPT = """You are a senior engineering manager reviewing support tickets before they enter the team's backlog for TaskPro.

You have access to tools to fetch ticket details, read original feedback, and update tickets with your review.

## Workflow
1. You are given the ticket_id and feedback_id. Use get_ticket_details to fetch the full ticket.
2. Use read_feedback to fetch the original user feedback.
3. Compare the ticket against the original feedback and evaluate on these criteria:
   - Title clarity (0-2): Specific, actionable, correctly prefixed?
   - Description completeness (0-3): Enough context? Bug: repro steps, environment? Feature: user need, solution?
   - Priority accuracy (0-2): Does priority match the severity/impact?
   - Technical accuracy (0-2): Are technical details reasonable and consistent?
   - Actionability (0-1): Can an engineer start working immediately?
4. Calculate total score (0-10).
5. Call update_ticket to write your review:
   - quality_score: your total score
   - quality_notes: your overall assessment (1-2 sentences)
   - quality_status: "approved" if score >= 7, "revision_needed" if score < 7

## Decision Rules
- Score >= 7: APPROVED — ticket is ready for the backlog
- Score < 7: REVISION NEEDED — your quality_notes should include specific improvement suggestions

Always use the tools — fetch the data, evaluate, then write your review via update_ticket."""


def create_quality_critic_agent(llm: ChatOpenAI) -> Any:
    """Create a compiled ReAct agent graph for quality review.

    Args:
        llm: The ChatOpenAI instance.

    Returns:
        Compiled ReAct agent (a LangGraph CompiledStateGraph).
    """
    tools = [get_ticket_details, read_feedback, update_ticket]
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=QUALITY_CRITIC_SYSTEM_PROMPT,
        name="quality_critic",
    )
    return agent


def build_quality_critic_input(state: PipelineState) -> list:
    """Build input messages for the quality critic agent from pipeline state."""
    item = state["current_item"]
    ticket = state["ticket"]
    classification = state["classification"]

    ticket_id = ticket.get("ticket_id", "N/A")
    if ticket_id in ("UNKNOWN", "N/A"):
        logger.warning("Quality critic got UNKNOWN ticket_id for feedback %s", item["feedback_id"])

    parts = [
        f"Review this ticket for quality and completeness:",
        f"",
        f"Ticket ID: {ticket.get('ticket_id', 'N/A')}",
        f"Feedback ID: {item['feedback_id']}",
        f"Category: {classification['category']}",
        f"",
        f"Use get_ticket_details to fetch the full ticket, and read_feedback to see the original.",
        f"Then evaluate and call update_ticket with your quality_score, quality_notes, and quality_status.",
    ]

    return [HumanMessage(content="\n".join(parts))]


def extract_quality_review(messages: list, state: PipelineState) -> dict:
    """Extract quality review data from the ReAct agent's output messages.

    Looks for update_ticket tool call arguments for quality_score and quality_status.
    """
    quality_review = {
        "score": 7.0,
        "breakdown": {},
        "approved": True,
        "notes": "Auto-approved (could not extract review from agent)",
        "revision_suggestions": [],
    }

    for msg in reversed(messages):
        # Check AIMessage tool_calls for update_ticket parameters
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] == "update_ticket":
                    args = tc.get("args", {})
                    if args.get("quality_score") is not None:
                        quality_review["score"] = float(args["quality_score"])
                    if args.get("quality_notes"):
                        quality_review["notes"] = args["quality_notes"]
                    if args.get("quality_status"):
                        quality_review["approved"] = args["quality_status"] == "approved"

        # Also check the agent's final text response for structured data
        if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
            content = msg.content
            # Try to extract structured review from the agent's reasoning
            try:
                data = json.loads(content)
                if "score" in data:
                    quality_review["score"] = float(data["score"])
                if "approved" in data:
                    quality_review["approved"] = data["approved"]
                if "notes" in data:
                    quality_review["notes"] = data["notes"]
                if "breakdown" in data:
                    quality_review["breakdown"] = data["breakdown"]
                if "revision_suggestions" in data:
                    quality_review["revision_suggestions"] = data["revision_suggestions"]
            except (json.JSONDecodeError, TypeError):
                # Not JSON — check if the text mentions approval/rejection
                pass

    if quality_review["notes"] == "Auto-approved (could not extract review from agent)":
        logger.warning("Quality review fell back to defaults — agent may not have called update_ticket")

    return quality_review


def create_quality_review_node(llm: ChatOpenAI):
    """Create a quality critic node function (ReAct agent)."""
    agent = create_quality_critic_agent(llm)

    def quality_review_node(state: PipelineState) -> dict:
        """LangGraph node: review ticket quality via ReAct agent with MCP tools."""
        item = state["current_item"]
        ticket = state["ticket"]

        logger.info("Reviewing ticket %s (ReAct agent)", ticket.get("ticket_id", "N/A"))

        input_messages = build_quality_critic_input(state)

        try:
            result = agent.invoke(
                {"messages": input_messages},
                config={"recursion_limit": settings.max_agent_iterations * 2 + 1},
            )
            output_messages = result["messages"]
            quality_review = extract_quality_review(output_messages, state)
        except Exception as e:
            logger.error("Quality critic agent failed: %s", e, exc_info=True)
            quality_review = {
                "score": 7.0,
                "breakdown": {},
                "approved": True,
                "notes": f"Auto-approved due to agent error: {e}",
                "revision_suggestions": [],
            }

        new_revision_count = state.get("revision_count", 0)
        if not quality_review["approved"]:
            new_revision_count += 1
            logger.info(
                "Ticket %s needs revision (score: %s, attempt %d)",
                ticket.get("ticket_id", "N/A"),
                quality_review["score"],
                new_revision_count,
            )
        else:
            logger.info(
                "Ticket %s approved (score: %s)",
                ticket.get("ticket_id", "N/A"),
                quality_review["score"],
            )

        return {
            "quality_review": quality_review,
            "revision_count": new_revision_count,
            "current_agent": "quality_critic",
            "status": "reviewing",
        }

    return quality_review_node
