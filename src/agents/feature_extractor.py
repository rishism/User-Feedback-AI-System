"""Feature Extractor Agent — ReAct agent that identifies feature requests via direct reasoning.

The LLM analyzes feature requests directly. It can optionally call
search_similar_tickets to check for duplicate feature requests.
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from src.config import settings
from src.db.queries import log_processing, update_feedback_status
from src.models.state import PipelineState
from src.observability.metrics import LatencyTimer
from src.tools.db_tools import read_feedback, search_similar_tickets

logger = logging.getLogger(__name__)

FEATURE_EXTRACTOR_SYSTEM_PROMPT = """You are a product manager analyzing user feedback for feature requests for a productivity mobile app called TaskPro.

Extract structured information from the feedback:

1. Feature name: Concise name (3-5 words)
2. Description: What the user wants and why (2-3 sentences)
3. User impact: High (many users, core workflow) | Medium (moderate benefit) | Low (niche/edge case)
4. Demand signal: Strong (urgent, explicit request) | Moderate (suggestion) | Weak (implied, vague)
5. Existing alternatives: Any workarounds mentioned
6. Suggested title: Clear feature request ticket title (under 80 chars)
7. Suggested priority: High | Medium | Low
8. Suggested actions: 2-3 concrete next steps

## Available Tools
- search_similar_tickets: Check if similar feature requests already exist
- read_feedback: Fetch the full raw feedback record if you need more context

## Response Format
After analyzing (and optionally using tools), respond with ONLY valid JSON:
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


def create_feature_extractor_agent(llm: ChatOpenAI) -> Any:
    """Create a compiled ReAct agent graph for feature extraction."""
    tools = [search_similar_tickets, read_feedback]
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=FEATURE_EXTRACTOR_SYSTEM_PROMPT,
        name="feature_extractor",
    )
    return agent


def build_feature_extractor_input(state: PipelineState) -> list:
    """Build input messages for the feature extractor agent."""
    item = state["current_item"]
    classification = state["classification"]

    parts = [f"User Feedback:\n{item['content_text']}"]
    if item.get("rating") is not None:
        parts.append(f"Rating: {item['rating']}/5")
    if item.get("platform"):
        parts.append(f"Platform: {item['platform']}")
    parts.append(f"\nClassification reasoning: {classification.get('reasoning', 'N/A')}")

    return [HumanMessage(content="\n".join(parts))]


def extract_feature_analysis(messages: list) -> dict:
    """Extract feature analysis from the agent's final AIMessage."""
    default_result = {
        "feature_name": "Unknown Feature",
        "description": "Unable to parse from feedback",
        "user_impact": "Medium",
        "demand_signal": "Moderate",
        "existing_alternatives": "None identified",
        "suggested_title": "Feature request",
        "suggested_priority": "Medium",
        "suggested_actions": ["Review and assess feasibility"],
    }

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
            try:
                result = json.loads(msg.content)
                if "feature_name" in result or "user_impact" in result:
                    return result
            except (json.JSONDecodeError, TypeError):
                for line in msg.content.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            result = json.loads(line)
                            if "feature_name" in result:
                                return result
                        except json.JSONDecodeError:
                            continue

    return default_result


def create_feature_extract_node(llm: ChatOpenAI):
    """Create a feature extractor node function (ReAct agent)."""
    agent = create_feature_extractor_agent(llm)

    def feature_extract_node(state: PipelineState) -> dict:
        """LangGraph node: extract feature details via ReAct agent."""
        item = state["current_item"]
        logger.info("Extracting feature request for feedback %s (ReAct agent)", item["source_id"])

        input_messages = build_feature_extractor_input(state)

        with LatencyTimer() as timer:
            try:
                result = agent.invoke(
                    {"messages": input_messages},
                    config={"recursion_limit": settings.max_agent_iterations * 2 + 1},
                )
                output_messages = result["messages"]
                feature_result = extract_feature_analysis(output_messages)
            except Exception as e:
                logger.error("Feature extractor agent failed: %s", e, exc_info=True)
                feature_result = {
                    "feature_name": "Unknown Feature",
                    "description": item["content_text"][:200],
                    "user_impact": "Medium",
                    "suggested_title": f"Feature: {item['content_text'][:60]}",
                    "suggested_priority": "Medium",
                    "suggested_actions": ["Review and assess feasibility"],
                }

        analysis = {
            "technical_details": None,
            "feature_details": feature_result,
            "suggested_title": feature_result.get("suggested_title", ""),
            "suggested_priority": feature_result.get("suggested_priority", "Medium"),
            "suggested_actions": feature_result.get("suggested_actions", []),
        }

        update_feedback_status(item["feedback_id"], "analyzed")
        log_processing(
            agent_name="feature_extractor",
            action="extract",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"category=Feature Request, source={item['source_id']}",
            output_summary=f"feature={feature_result.get('feature_name')}, impact={feature_result.get('user_impact')}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        return {
            "analysis": analysis,
            "current_agent": "feature_extractor",
            "status": "analyzing",
        }

    return feature_extract_node
