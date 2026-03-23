"""Bug Analyzer Agent — extracts technical details from bug reports."""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.db.queries import log_processing, update_feedback_status
from src.observability.metrics import LatencyTimer
from src.models.state import PipelineState

logger = logging.getLogger(__name__)

BUG_ANALYZER_SYSTEM_PROMPT = """You are a senior QA engineer analyzing a bug report from user feedback for a productivity mobile app called TaskPro.

Extract the following structured information from the feedback:

1. Severity: Critical (app unusable, data loss, security) | Major (key feature broken, no workaround) | Minor (workaround exists) | Cosmetic (visual only)
2. Affected component: e.g., Login, Sync, UI, Notifications, Dashboard, Settings, Tasks, Search, Performance
3. Platform details: Extract any mentioned device model, OS version, app version
4. Steps to reproduce: Infer reasonable steps from the text, list as numbered steps
5. Expected vs actual behavior: What should happen vs what actually happens
6. Suggested title: A clear, concise bug ticket title (under 80 chars)
7. Suggested priority: Critical (data loss/security) | High (major feature broken) | Medium (degraded experience) | Low (minor issue)
8. Suggested actions: 2-3 concrete next steps for the engineering team

You MUST respond with valid JSON only, no other text:
{
    "severity": "Critical|Major|Minor|Cosmetic",
    "affected_component": "component name",
    "platform_details": {"device": "...", "os": "...", "app_version": "..."},
    "steps_to_reproduce": ["Step 1", "Step 2"],
    "expected_behavior": "...",
    "actual_behavior": "...",
    "suggested_title": "...",
    "suggested_priority": "Critical|High|Medium|Low",
    "suggested_actions": ["action 1", "action 2"]
}"""


def create_bug_analyze_node(llm: ChatOpenAI):
    """Create a bug analyzer node function bound to the given LLM."""

    def bug_analyze_node(state: PipelineState) -> dict:
        """LangGraph node: analyze bug details from the current feedback item."""
        item = state["current_item"]
        logger.info(f"Analyzing bug for feedback {item['source_id']}")

        user_msg = f"Bug Report:\n{item['content_text']}"
        if item.get("rating") is not None:
            user_msg += f"\nRating: {item['rating']}/5"
        if item.get("platform"):
            user_msg += f"\nPlatform: {item['platform']}"
        if item.get("app_version"):
            user_msg += f"\nApp Version: {item['app_version']}"

        with LatencyTimer() as timer:
            response = llm.invoke([
                SystemMessage(content=BUG_ANALYZER_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ])

        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error(f"Bug analyzer returned invalid JSON: {response.content}")
            result = {
                "severity": "Major",
                "affected_component": "Unknown",
                "platform_details": {},
                "steps_to_reproduce": ["Unable to parse from feedback"],
                "expected_behavior": "Normal operation",
                "actual_behavior": item["content_text"][:200],
                "suggested_title": f"Bug: {item['content_text'][:60]}",
                "suggested_priority": "Medium",
                "suggested_actions": ["Investigate and reproduce the issue"],
            }

        analysis = {
            "technical_details": result,
            "feature_details": None,
            "suggested_title": result.get("suggested_title", ""),
            "suggested_priority": result.get("suggested_priority", "Medium"),
            "suggested_actions": result.get("suggested_actions", []),
        }

        update_feedback_status(item["feedback_id"], "analyzed")
        log_processing(
            agent_name="bug_analyzer",
            action="analyze",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"category=Bug, source={item['source_id']}",
            output_summary=f"severity={result.get('severity')}, component={result.get('affected_component')}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        return {
            "analysis": analysis,
            "current_agent": "bug_analyzer",
            "status": "analyzing",
        }

    return bug_analyze_node
