"""Feature Extractor Agent — identifies feature requests and estimates user impact."""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.db.queries import log_processing, update_feedback_status
from src.observability.metrics import LatencyTimer
from src.models.state import PipelineState

logger = logging.getLogger(__name__)

FEATURE_EXTRACTOR_SYSTEM_PROMPT = """You are a product manager analyzing user feedback for feature requests for a productivity mobile app called TaskPro.

Extract the following structured information:

1. Feature name: A concise name for the requested feature (3-5 words)
2. Description: What the user wants and why, in 2-3 sentences
3. User impact: High (many users affected, core workflow improvement) | Medium (moderate benefit, nice-to-have for many) | Low (niche/edge case)
4. Demand signal: Strong (urgent language, explicit request) | Moderate (suggestion, would be nice) | Weak (implied, vague)
5. Existing alternatives: Any workarounds the user mentions or that exist
6. Suggested title: A clear feature request ticket title (under 80 chars)
7. Suggested priority: High (high impact + strong demand) | Medium (moderate impact or demand) | Low (low impact or weak demand)
8. Suggested actions: 2-3 concrete next steps for the product team

You MUST respond with valid JSON only, no other text:
{
    "feature_name": "...",
    "description": "...",
    "user_impact": "High|Medium|Low",
    "demand_signal": "Strong|Moderate|Weak",
    "existing_alternatives": "...",
    "suggested_title": "...",
    "suggested_priority": "High|Medium|Low",
    "suggested_actions": ["action 1", "action 2"]
}"""


def create_feature_extract_node(llm: ChatOpenAI):
    """Create a feature extractor node function bound to the given LLM."""

    def feature_extract_node(state: PipelineState) -> dict:
        """LangGraph node: extract feature details from the current feedback item."""
        item = state["current_item"]
        logger.info(f"Extracting feature request for feedback {item['source_id']}")

        user_msg = f"User Feedback:\n{item['content_text']}"
        if item.get("rating") is not None:
            user_msg += f"\nRating: {item['rating']}/5"
        if item.get("platform"):
            user_msg += f"\nPlatform: {item['platform']}"

        with LatencyTimer() as timer:
            response = llm.invoke([
                SystemMessage(content=FEATURE_EXTRACTOR_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error(f"Feature extractor returned invalid JSON: {response.content}")
            result = {
                "feature_name": "Unknown Feature",
                "description": item["content_text"][:200],
                "user_impact": "Medium",
                "demand_signal": "Moderate",
                "existing_alternatives": "None identified",
                "suggested_title": f"Feature: {item['content_text'][:60]}",
                "suggested_priority": "Medium",
                "suggested_actions": ["Review and assess feasibility"],
            }

        analysis = {
            "technical_details": None,
            "feature_details": result,
            "suggested_title": result.get("suggested_title", ""),
            "suggested_priority": result.get("suggested_priority", "Medium"),
            "suggested_actions": result.get("suggested_actions", []),
        }

        update_feedback_status(item["feedback_id"], "analyzed")
        log_processing(
            agent_name="feature_extractor",
            action="extract",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"category=Feature Request, source={item['source_id']}",
            output_summary=f"feature={result.get('feature_name')}, impact={result.get('user_impact')}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        return {
            "analysis": analysis,
            "current_agent": "feature_extractor",
            "status": "analyzing",
        }

    return feature_extract_node
