"""Quality Critic Agent — reviews generated tickets for completeness and accuracy."""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.db.queries import log_processing, update_feedback_status, update_ticket
from src.observability.metrics import LatencyTimer
from src.models.state import PipelineState

logger = logging.getLogger(__name__)

QUALITY_CRITIC_SYSTEM_PROMPT = """You are a senior engineering manager reviewing support tickets before they enter the team's backlog for a productivity app called TaskPro.

Evaluate the ticket on these criteria (score each):
1. Title clarity (0-2): Is it specific, actionable, and correctly prefixed with category?
2. Description completeness (0-3): Does it contain enough context? For bugs: reproduction steps, environment? For features: user need, proposed solution?
3. Priority accuracy (0-2): Does the assigned priority match the content severity/impact?
4. Technical accuracy (0-2): Are technical details reasonable and consistent with the feedback?
5. Actionability (0-1): Can an engineer pick this up and start working immediately?

Total score: 0-10.

Decision rules:
- Score >= 7: APPROVED — ticket is ready for the backlog
- Score < 7: REVISION NEEDED — provide specific, actionable feedback on what to improve

You MUST respond with valid JSON only, no other text:
{
    "score": <0-10>,
    "breakdown": {
        "title_clarity": <0-2>,
        "description_completeness": <0-3>,
        "priority_accuracy": <0-2>,
        "technical_accuracy": <0-2>,
        "actionability": <0-1>
    },
    "approved": true|false,
    "notes": "Overall assessment in 1-2 sentences",
    "revision_suggestions": ["specific suggestion 1", "specific suggestion 2"]
}"""


def create_quality_review_node(llm: ChatOpenAI):
    """Create a quality critic node function bound to the given LLM."""

    def quality_review_node(state: PipelineState) -> dict:
        """LangGraph node: review the generated ticket for quality."""
        item = state["current_item"]
        ticket = state["ticket"]
        classification = state["classification"]

        logger.info(f"Reviewing ticket {ticket['ticket_id']}")

        user_msg = (
            f"ORIGINAL FEEDBACK:\n{item['content_text']}\n\n"
            f"CLASSIFICATION: {classification['category']} "
            f"(confidence: {classification['confidence']})\n\n"
            f"GENERATED TICKET:\n"
            f"Title: {ticket['title']}\n"
            f"Description: {ticket['description']}\n"
            f"Priority: {ticket['priority']}\n"
            f"Category: {ticket['category']}\n"
        )

        with LatencyTimer() as timer:
            response = llm.invoke([
                SystemMessage(content=QUALITY_CRITIC_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error(f"Quality critic returned invalid JSON: {response.content}")
            result = {
                "score": 7.0,
                "breakdown": {},
                "approved": True,
                "notes": "Auto-approved due to parse error",
                "revision_suggestions": [],
            }

        # Apply auto-approve threshold from config
        score = result["score"]
        approved = score >= settings.quality_auto_approve_threshold

        quality_review = {
            "score": score,
            "breakdown": result.get("breakdown", {}),
            "approved": approved,
            "notes": result.get("notes", ""),
            "revision_suggestions": result.get("revision_suggestions", []),
        }

        # Update ticket in DB with quality info
        quality_status = "approved" if approved else "revision_needed"
        update_ticket(
            ticket["ticket_id"],
            quality_score=score,
            quality_notes=result.get("notes", ""),
            quality_status=quality_status,
        )

        update_feedback_status(item["feedback_id"], "reviewed")
        log_processing(
            agent_name="quality_critic",
            action="review",
            status="success",
            feedback_id=item["feedback_id"],
            ticket_id=ticket["ticket_id"],
            input_summary=f"ticket={ticket['ticket_id']}",
            output_summary=f"score={score}, approved={approved}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        new_revision_count = state["revision_count"]
        if not approved:
            new_revision_count += 1
            logger.info(
                f"Ticket {ticket['ticket_id']} needs revision "
                f"(score: {score}, attempt {new_revision_count})"
            )
        else:
            logger.info(f"Ticket {ticket['ticket_id']} approved (score: {score})")

        return {
            "quality_review": quality_review,
            "revision_count": new_revision_count,
            "current_agent": "quality_critic",
            "status": "reviewing",
        }

    return quality_review_node
