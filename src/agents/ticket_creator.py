"""Ticket Creator Agent — ReAct agent that creates tickets via MCP tool-calling.

The LLM autonomously decides to call the create_ticket MCP tool with
appropriate parameters, and may also check for duplicates via get_tickets.
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from src.config import settings
from src.models.state import PipelineState
from src.tools.db_tools import read_feedback, search_similar_tickets
from src.tools.mcp_tools import create_ticket, get_tickets, update_ticket

logger = logging.getLogger(__name__)

TICKET_CREATOR_SYSTEM_PROMPT = """You are a technical writer creating structured support tickets from user feedback for a productivity app called TaskPro.

You have access to tools to create and manage tickets. You MUST use the create_ticket tool to persist each ticket.

## Workflow
1. Review the feedback, classification, and analysis provided
2. Optionally call search_similar_tickets to check for duplicates
3. Call create_ticket with well-crafted parameters:
   - title: Clear, actionable, under 80 chars. Format: "[Category] Brief description"
   - description: Structured with sections:
     * Summary (1-2 sentences)
     * For Bugs: Steps to Reproduce, Expected Behavior, Actual Behavior, Environment
     * For Feature Requests: User Need, Proposed Solution, Impact Assessment
     * For Praise: Key Positive Points, Areas Highlighted
     * For Complaints: Issue Description, User Impact, Suggested Resolution
     * For Spam: Reason for Classification
   - priority: Based on severity (bugs) or impact (features) or Low (praise/spam)
4. After creating the ticket, confirm the ticket_id in your response

## If Revising a Previously Rejected Ticket
Address the quality critic's feedback. Use the update_ticket tool to update the existing ticket
rather than creating a new one. Incorporate all revision suggestions.

Always use the tools — never just describe what you would do."""


def create_ticket_agent(llm: ChatOpenAI) -> Any:
    """Create a compiled ReAct agent graph for ticket creation.

    Args:
        llm: The ChatOpenAI instance.

    Returns:
        Compiled ReAct agent (a LangGraph CompiledStateGraph).
    """
    tools = [create_ticket, update_ticket, get_tickets, search_similar_tickets]
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=TICKET_CREATOR_SYSTEM_PROMPT,
        name="ticket_creator",
    )
    return agent


def build_ticket_creator_input(state: PipelineState) -> list:
    """Build input messages for the ticket creator agent from pipeline state."""
    item = state["current_item"]
    classification = state["classification"]
    analysis = state.get("analysis")
    quality_review = state.get("quality_review")
    revision_count = state.get("revision_count", 0)

    parts = [
        f"Create a ticket for this feedback:",
        f"",
        f"Feedback ID: {item['feedback_id']}",
        f"Source: {item.get('source_type', 'unknown')} / {item.get('source_id', 'N/A')}",
        f"Content: {item['content_text']}",
        f"",
        f"Classification: {classification['category']} (confidence: {classification['confidence']})",
        f"Reasoning: {classification['reasoning']}",
    ]

    if item.get("rating") is not None:
        parts.append(f"Rating: {item['rating']}/5")
    if item.get("platform"):
        parts.append(f"Platform: {item['platform']}")

    if analysis:
        if analysis.get("technical_details"):
            parts.append(f"\nBug Analysis: {json.dumps(analysis['technical_details'])}")
        if analysis.get("feature_details"):
            parts.append(f"\nFeature Analysis: {json.dumps(analysis['feature_details'])}")
        if analysis.get("suggested_title"):
            parts.append(f"Suggested Title: {analysis['suggested_title']}")
        if analysis.get("suggested_priority"):
            parts.append(f"Suggested Priority: {analysis['suggested_priority']}")

    # If revision, include quality critic feedback
    if quality_review and not quality_review.get("approved") and revision_count > 0:
        existing_ticket = state.get("ticket", {})
        parts.append(f"\n--- REVISION NEEDED (attempt {revision_count}) ---")
        parts.append(f"Existing ticket ID: {existing_ticket.get('ticket_id', 'N/A')}")
        parts.append(f"Quality Score: {quality_review.get('score', 'N/A')}/10")
        parts.append(f"Notes: {quality_review.get('notes', 'N/A')}")
        suggestions = quality_review.get("revision_suggestions", [])
        if suggestions:
            parts.append(f"Suggestions: {', '.join(suggestions)}")
        parts.append(f"Use update_ticket to revise the existing ticket.")

    return [HumanMessage(content="\n".join(parts))]


def extract_ticket_data(messages: list, state: PipelineState) -> dict:
    """Extract ticket data from the ReAct agent's output messages.

    Looks for create_ticket or update_ticket tool call arguments and results.
    """
    item = state["current_item"]
    classification = state["classification"]

    ticket_data = {
        "ticket_id": "UNKNOWN",
        "feedback_id": item["feedback_id"],
        "category": classification["category"],
        "confidence": classification["confidence"],
        "title": f"[{classification['category']}] {item['content_text'][:60]}",
        "description": item["content_text"],
        "priority": "Medium",
    }

    # Walk messages backwards to find the most recent tool call/result
    for msg in reversed(messages):
        # Check ToolMessage results for ticket_id
        if isinstance(msg, ToolMessage) and msg.name in ("create_ticket", "update_ticket"):
            try:
                raw_content = msg.content
                # LangChain agents may return content as a list of blocks
                if isinstance(raw_content, list):
                    raw_content = next(
                        (block["text"] for block in raw_content
                         if isinstance(block, dict) and block.get("type") == "text"),
                        str(raw_content),
                    )
                result = json.loads(raw_content)
                if result.get("ticket_id"):
                    ticket_data["ticket_id"] = result["ticket_id"]
                elif result.get("error"):
                    logger.warning("MCP %s error: %s", msg.name, result["error"])
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Cannot parse %s result: %s (content=%s)",
                               msg.name, e, str(msg.content)[:200])

        # Check AIMessage tool_calls for the parameters used
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] in ("create_ticket", "update_ticket"):
                    args = tc.get("args", {})
                    if args.get("title"):
                        ticket_data["title"] = args["title"]
                    if args.get("description"):
                        ticket_data["description"] = args["description"]
                    if args.get("priority"):
                        ticket_data["priority"] = args["priority"]

    return ticket_data


def create_ticket_node(llm: ChatOpenAI):
    """Create a ticket creator node function (ReAct agent).

    Args:
        llm: The ChatOpenAI instance.
    """
    agent = create_ticket_agent(llm)

    def ticket_create_node(state: PipelineState) -> dict:
        """LangGraph node: create a ticket via ReAct agent with MCP tools."""
        item = state["current_item"]
        logger.info("Creating ticket for feedback %s (ReAct agent)", item["source_id"])

        input_messages = build_ticket_creator_input(state)

        try:
            result = agent.invoke(
                {"messages": input_messages},
                config={"recursion_limit": settings.max_agent_iterations * 2 + 1},
            )
            output_messages = result["messages"]
            ticket_data = extract_ticket_data(output_messages, state)
        except Exception as e:
            logger.error("Ticket creator agent failed: %s", e, exc_info=True)
            # Fallback: create minimal ticket data
            ticket_data = {
                "ticket_id": "UNKNOWN",
                "feedback_id": item["feedback_id"],
                "category": state["classification"]["category"],
                "confidence": state["classification"]["confidence"],
                "title": f"[{state['classification']['category']}] {item['content_text'][:60]}",
                "description": item["content_text"],
                "priority": "Medium",
            }

        if ticket_data["ticket_id"] == "UNKNOWN":
            logger.warning("UNKNOWN ticket_id for feedback %s — MCP tool may have failed",
                           item["feedback_id"])
        else:
            logger.info("Created ticket %s: %s", ticket_data["ticket_id"], ticket_data["title"][:60])

        return {
            "ticket": ticket_data,
            "current_agent": "ticket_creator",
            "status": "ticketing",
        }

    return ticket_create_node
