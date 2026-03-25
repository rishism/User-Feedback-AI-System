"""Supervisor Agent — LLM-driven routing at branching points.

Called at two decision points in the pipeline:
1. Post-classification: choose bug_analyzer, feature_extractor, or ticket_creator
2. Post-quality-review: choose finalize or ticket_creator (revision)
"""

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.models.state import PipelineState

logger = logging.getLogger(__name__)

# All legal routing targets
VALID_AGENTS = {"bug_analyzer", "feature_extractor", "ticket_creator", "finalize"}

SUPERVISOR_SYSTEM_PROMPT = """You are the Feedback Processing Supervisor. You route feedback items
to the correct specialist agent based on the current processing state.

You make decisions at two points:

## Decision 1: After Classification
When a feedback item has been classified but not yet analyzed or ticketed,
choose the next agent:
- "bug_analyzer" — if category is Bug (needs technical analysis before ticketing)
- "feature_extractor" — if category is Feature Request (needs impact analysis before ticketing)
- "ticket_creator" — if category is Praise, Complaint, or Spam (skip analysis, go straight to ticketing)

## Decision 2: After Quality Review
When a ticket has been created and reviewed by the quality critic, decide:
- "finalize" — if the quality review approved the ticket OR max revisions reached
- "ticket_creator" — if the quality review rejected the ticket and revisions remain

Be decisive. Always choose exactly one agent. Explain your reasoning briefly."""


class SupervisorDecision(BaseModel):
    """Structured output from the supervisor."""
    next_agent: str = Field(description="The next agent to route to")
    reasoning: str = Field(description="Brief explanation for the routing decision")


def create_supervisor_node(llm: ChatOpenAI):
    """Create a supervisor node that routes based on pipeline state."""

    structured_llm = llm.with_structured_output(SupervisorDecision)

    def supervisor_node(state: PipelineState) -> dict:
        """LangGraph node: decide which agent to invoke next."""
        classification = state.get("classification")
        ticket = state.get("ticket")
        quality_review = state.get("quality_review")
        revision_count = state.get("revision_count", 0)

        # Build context for the supervisor
        context_parts = []

        if state.get("current_item"):
            item = state["current_item"]
            context_parts.append(
                f"Current feedback: {item['content_text'][:200]}"
            )

        if classification:
            context_parts.append(
                f"Classification: {classification['category']} "
                f"(confidence: {classification['confidence']})"
            )

        if state.get("analysis"):
            context_parts.append(f"Analysis completed: {bool(state['analysis'])}")

        if ticket:
            context_parts.append(
                f"Ticket created: {ticket.get('ticket_id', 'N/A')} — "
                f"{ticket.get('title', 'N/A')}"
            )

        if quality_review:
            context_parts.append(
                f"Quality review: score={quality_review.get('score', 'N/A')}, "
                f"approved={quality_review.get('approved', 'N/A')}, "
                f"notes={quality_review.get('notes', 'N/A')[:100]}"
            )

        context_parts.append(f"Revision count: {revision_count}")
        context_parts.append(
            f"Max revisions: {state.get('max_revision_count', 2)}"
            if "max_revision_count" in state
            else "Max revisions: 2"
        )

        context_msg = "\n".join(context_parts)

        decision = structured_llm.invoke([
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=f"Current state:\n{context_msg}\n\nWhich agent should handle this next?"),
        ])

        next_agent = decision.next_agent
        reasoning = decision.reasoning

        # Guard rail: validate the decision
        if next_agent not in VALID_AGENTS:
            logger.warning(
                "Supervisor returned invalid agent '%s', falling back. Context: %s",
                next_agent, context_msg,
            )
            # Sensible fallback based on state
            if quality_review and ticket:
                next_agent = "finalize"
            elif classification:
                next_agent = "ticket_creator"
            else:
                next_agent = "ticket_creator"
            reasoning = f"(fallback) Original decision was invalid. Defaulting to {next_agent}."

        logger.info("Supervisor decision: %s — %s", next_agent, reasoning)

        return {
            "next_agent": next_agent,
            "supervisor_reasoning": reasoning,
            "current_agent": "supervisor",
            "status": "routing",
        }

    return supervisor_node
