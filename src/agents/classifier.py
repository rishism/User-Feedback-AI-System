"""Feedback Classifier Agent — ReAct agent that classifies via direct reasoning.

The LLM classifies feedback in its response. It can optionally call
search_similar_tickets to calibrate when confidence is low.
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

CLASSIFIER_SYSTEM_PROMPT = """You are an expert feedback classifier for a productivity mobile application called TaskPro.

Classify the user feedback into exactly ONE category:

- Bug: Technical issues, crashes, errors, broken features, data loss, performance problems
- Feature Request: Suggestions for new features, improvements, enhancements, integrations
- Praise: Positive feedback, compliments, satisfaction, appreciation
- Complaint: Dissatisfaction about non-technical issues (pricing, customer service, UX quality)
- Spam: Promotional content, irrelevant text, gibberish, partnership solicitations

## Guidelines
- Consider the rating (if available): 1-2 stars often correlate with bugs/complaints, 4-5 with praise
- Specific technical failures (crashes, errors, data loss) → Bug even if tone is complaining
- Requests for something that doesn't exist yet → Feature Request
- Pricing, support quality, general dissatisfaction (no technical issues) → Complaint
- Be decisive — pick the single best category

## Available Tools
- search_similar_tickets: If uncertain, check how similar feedback was classified before
- read_feedback: If you need the full raw feedback record for more context

## Response Format
After analyzing (and optionally using tools), respond with ONLY valid JSON:
{
    "category": "<Bug|Feature Request|Praise|Complaint|Spam>",
    "confidence": <0.0-1.0>,
    "reasoning": "<brief 1-2 sentence explanation>"
}"""


def create_classifier_agent(llm: ChatOpenAI) -> Any:
    """Create a compiled ReAct agent graph for classification."""
    tools = [search_similar_tickets, read_feedback]
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=CLASSIFIER_SYSTEM_PROMPT,
        name="classifier",
    )
    return agent


def build_classifier_input(state: PipelineState) -> list:
    """Build input messages for the classifier agent."""
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

    return [HumanMessage(content="\n".join(parts))]


def extract_classification(messages: list) -> dict:
    """Extract classification from the agent's final AIMessage."""
    default = {
        "category": "Complaint",
        "confidence": 0.5,
        "reasoning": "Could not parse agent output, defaulting to Complaint",
    }

    # Walk backwards to find the last AIMessage without tool calls
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
            try:
                result = json.loads(msg.content)
                return {
                    "category": result.get("category", default["category"]),
                    "confidence": result.get("confidence", default["confidence"]),
                    "reasoning": result.get("reasoning", default["reasoning"]),
                }
            except (json.JSONDecodeError, TypeError):
                # Try to extract from mixed content (text + JSON)
                content = msg.content
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            result = json.loads(line)
                            if "category" in result:
                                return {
                                    "category": result["category"],
                                    "confidence": result.get("confidence", 0.7),
                                    "reasoning": result.get("reasoning", ""),
                                }
                        except json.JSONDecodeError:
                            continue

    return default


def create_classify_node(llm: ChatOpenAI):
    """Create a classifier node function (ReAct agent)."""
    agent = create_classifier_agent(llm)

    def classify_node(state: PipelineState) -> dict:
        """LangGraph node: classify feedback via ReAct agent."""
        item = state["current_item"]
        logger.info("Classifying feedback %s (ReAct agent)", item["source_id"])

        input_messages = build_classifier_input(state)

        with LatencyTimer() as timer:
            try:
                result = agent.invoke(
                    {"messages": input_messages},
                    config={"recursion_limit": settings.max_agent_iterations * 2 + 1},
                )
                output_messages = result["messages"]
                classification = extract_classification(output_messages)
            except Exception as e:
                logger.error("Classifier agent failed: %s", e, exc_info=True)
                classification = {
                    "category": "Complaint",
                    "confidence": 0.5,
                    "reasoning": f"Agent error: {e}",
                }

        update_feedback_status(item["feedback_id"], "classified")
        log_processing(
            agent_name="classifier",
            action="classify",
            status="success",
            feedback_id=item["feedback_id"],
            input_summary=f"text_length={len(item['content_text'])}",
            output_summary=f"category={classification['category']}, confidence={classification['confidence']}",
            latency_ms=timer.elapsed_ms,
            trace_id=state.get("trace_id"),
        )

        logger.info(
            "Classified %s as %s (confidence: %s)",
            item["source_id"],
            classification["category"],
            classification["confidence"],
        )

        return {
            "classification": classification,
            "current_agent": "classifier",
            "status": "classifying",
        }

    return classify_node
