"""Bug Analyzer Agent — ReAct agent that extracts technical details via direct reasoning.

The LLM analyzes the bug report directly. It can optionally call
search_similar_tickets to see how similar bugs were handled.
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

BUG_ANALYZER_SYSTEM_PROMPT = """You are a senior QA engineer analyzing a bug report from user feedback for a productivity mobile app called TaskPro.

Extract structured information from the feedback:

1. Severity: Critical (app unusable, data loss, security) | Major (key feature broken) | Minor (workaround exists) | Cosmetic (visual only)
2. Affected component: e.g., Login, Sync, UI, Notifications, Dashboard, Settings, Tasks, Search, Performance
3. Platform details: Device model, OS version, app version
4. Steps to reproduce: Infer reasonable numbered steps from the text
5. Expected vs actual behavior
6. Suggested title: Clear bug ticket title (under 80 chars)
7. Suggested priority: Critical | High | Medium | Low
8. Suggested actions: 2-3 concrete next steps

## Available Tools
- search_similar_tickets: Check if similar bugs exist to inform severity assessment
- read_feedback: Fetch the full raw feedback record if you need more context

## Response Format
After analyzing (and optionally using tools), respond with ONLY valid JSON:
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


def create_bug_analyzer_agent(llm: ChatOpenAI) -> Any:
    """Create a compiled ReAct agent graph for bug analysis."""
    tools = [search_similar_tickets, read_feedback]
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=BUG_ANALYZER_SYSTEM_PROMPT,
        name="bug_analyzer",
    )
    return agent


def build_bug_analyzer_input(state: PipelineState) -> list:
    """Build input messages for the bug analyzer agent."""
    item = state["current_item"]
    classification = state["classification"]

    parts = [f"Bug Report:\n{item['content_text']}"]
    if item.get("rating") is not None:
        parts.append(f"Rating: {item['rating']}/5")
    if item.get("platform"):
        parts.append(f"Platform: {item['platform']}")
    if item.get("app_version"):
        parts.append(f"App Version: {item['app_version']}")
    parts.append(f"\nClassification reasoning: {classification.get('reasoning', 'N/A')}")

    return [HumanMessage(content="\n".join(parts))]


def extract_bug_analysis(messages: list) -> dict:
    """Extract bug analysis from the agent's final AIMessage."""
    default_result = {
        "severity": "Major",
        "affected_component": "Unknown",
        "platform_details": {},
        "steps_to_reproduce": ["Unable to parse from feedback"],
        "expected_behavior": "Normal operation",
        "actual_behavior": "Unknown",
        "suggested_title": "Bug report",
        "suggested_priority": "Medium",
        "suggested_actions": ["Investigate and reproduce the issue"],
    }

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
            try:
                result = json.loads(msg.content)
                if "severity" in result or "affected_component" in result:
                    return result
            except (json.JSONDecodeError, TypeError):
                # Try line-by-line for mixed content
                for line in msg.content.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            result = json.loads(line)
                            if "severity" in result:
                                return result
                        except json.JSONDecodeError:
                            continue

    return default_result


def create_bug_analyze_node(llm: ChatOpenAI):
    """Create a bug analyzer node function (ReAct agent)."""
    agent = create_bug_analyzer_agent(llm)

    def bug_analyze_node(state: PipelineState) -> dict:
        """LangGraph node: analyze bug via ReAct agent."""
        item = state["current_item"]
        logger.info("Analyzing bug for feedback %s (ReAct agent)", item["source_id"])

        input_messages = build_bug_analyzer_input(state)

        with LatencyTimer() as timer:
            try:
                result = agent.invoke(
                    {"messages": input_messages},
                    config={"recursion_limit": settings.max_agent_iterations * 2 + 1},
                )
                output_messages = result["messages"]
                bug_result = extract_bug_analysis(output_messages)
            except Exception as e:
                logger.error("Bug analyzer agent failed: %s", e, exc_info=True)
                bug_result = {
                    "severity": "Major",
                    "affected_component": "Unknown",
                    "suggested_title": f"Bug: {item['content_text'][:60]}",
                    "suggested_priority": "Medium",
                    "suggested_actions": ["Investigate the reported issue"],
                }

        analysis = {
            "technical_details": bug_result,
            "feature_details": None,
            "suggested_title": bug_result.get("suggested_title", ""),
            "suggested_priority": bug_result.get("suggested_priority", "Medium"),
            "suggested_actions": bug_result.get("suggested_actions", []),
        }

        update_feedback_status(item["feedback_id"], "analyzed")
        log_processing(
            agent_name="bug_analyzer",
            action="analyze",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"category=Bug, source={item['source_id']}",
            output_summary=f"severity={bug_result.get('severity')}, component={bug_result.get('affected_component')}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        return {
            "analysis": analysis,
            "current_agent": "bug_analyzer",
            "status": "analyzing",
        }

    return bug_analyze_node
