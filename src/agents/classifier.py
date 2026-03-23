"""Feedback Classifier Agent — LLM-based classification into 5 categories."""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.db.queries import log_processing, update_feedback_status
from src.observability.metrics import LatencyTimer, ProcessingMetric
from src.models.state import PipelineState

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """You are an expert feedback classifier for a productivity mobile application called TaskPro.
Classify the following user feedback into exactly ONE category:

- Bug: Technical issues, crashes, errors, broken features, data loss, performance problems
- Feature Request: Suggestions for new features, improvements, enhancements, integrations
- Praise: Positive feedback, compliments, satisfaction, appreciation
- Complaint: Dissatisfaction about non-technical issues (pricing, customer service, UX quality)
- Spam: Promotional content, irrelevant text, gibberish, partnership solicitations

Guidelines:
- Consider the rating (if available) as a secondary signal: 1-2 stars often correlate with bugs/complaints, 4-5 with praise
- If the feedback mentions specific technical failures (crashes, errors, data loss), classify as Bug even if the tone is complaining
- If the feedback asks for something that doesn't exist yet, classify as Feature Request
- Complaints about pricing, support quality, or general dissatisfaction (without specific technical issues) are Complaints
- Be decisive — pick the single best category

You MUST respond with valid JSON only, no other text:
{
    "category": "<Bug|Feature Request|Praise|Complaint|Spam>",
    "confidence": <0.0-1.0>,
    "reasoning": "<brief 1-2 sentence explanation>"
}"""


def _build_user_message(state: PipelineState) -> str:
    """Build the user message from the current feedback item."""
    item = state["current_item"]
    parts = []

    if item.get("subject"):
        parts.append(f"Subject: {item['subject']}")

    parts.append(f"Feedback: {item['content_text']}")

    if item.get("rating") is not None:
        parts.append(f"Rating: {item['rating']}/5 stars")
    if item.get("platform"):
        parts.append(f"Platform: {item['platform']}")
    if item.get("source_type"):
        parts.append(f"Source: {item['source_type']}")

    return "\n".join(parts)


def create_classify_node(llm: ChatOpenAI):
    """Create a classifier node function bound to the given LLM."""

    def classify_node(state: PipelineState) -> dict:
        """LangGraph node: classify the current feedback item."""
        item = state["current_item"]
        logger.info(f"Classifying feedback {item['source_id']}")

        user_msg = _build_user_message(state)

        with LatencyTimer() as timer:
            response = llm.invoke([
                SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error(f"Classifier returned invalid JSON: {response.content}")
            result = {
                "category": "Complaint",
                "confidence": 0.5,
                "reasoning": "Failed to parse LLM response, defaulting to Complaint",
            }

        classification = {
            "category": result["category"],
            "confidence": result["confidence"],
            "reasoning": result["reasoning"],
        }

        # Log to DB
        update_feedback_status(item["feedback_id"], "classified")
        log_processing(
            agent_name="classifier",
            action="classify",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"text_length={len(item['content_text'])}",
            output_summary=f"category={result['category']}, confidence={result['confidence']}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        logger.info(
            f"Classified {item['source_id']} as {result['category']} "
            f"(confidence: {result['confidence']})"
        )

        return {
            "classification": classification,
            "current_agent": "classifier",
            "status": "classifying",
        }

    return classify_node
