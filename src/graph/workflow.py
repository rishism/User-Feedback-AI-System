"""Agentic LangGraph pipeline with hybrid supervisor routing.

Architecture:
  ingest → classify → supervisor → (bug_analyzer|feature_extractor|ticket_creator)
  → ticket_creator → quality_critic → supervisor → (finalize|ticket_creator)
  → finalize → next_item → (ingest loop | END)

The supervisor makes LLM-driven routing decisions at two branching points:
1. Post-classification: which analyzer, or skip to ticketing?
2. Post-quality-review: approve or revise?

All other transitions are deterministic.
"""

import json
import logging
import time
import uuid
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from src.agents.bug_analyzer import create_bug_analyze_node
from src.agents.classifier import create_classify_node
from src.agents.csv_agent import ingest_node
from src.agents.feature_extractor import create_feature_extract_node
from src.agents.quality_critic import create_quality_review_node
from src.agents.supervisor import create_supervisor_node
from src.agents.ticket_creator import create_ticket_node
from src.config import settings
from src.db.queries import log_processing, update_feedback_status
from src.models.state import PipelineState
from src.observability.tracing import create_langfuse_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_from_supervisor(state: PipelineState) -> str:
    """Route based on the supervisor's decision."""
    return state["next_agent"]


def route_next_or_end(state: PipelineState) -> str:
    """Deterministic: more items to process, or end the pipeline."""
    if state["current_index"] < state["total_items"]:
        return "ingest"
    return "end"


# ---------------------------------------------------------------------------
# Helper nodes
# ---------------------------------------------------------------------------

def _agentic_ingest_node(state: PipelineState) -> dict:
    """Ingest node that also adds a context message for downstream agents."""
    result = ingest_node(state)
    current = result.get("current_item") or state.get("current_item")

    # Add a HumanMessage so agents and supervisor have context
    if current:
        parts = [f"Feedback to process (source: {current.get('source_type', 'unknown')}, "
                 f"id: {current.get('source_id', 'N/A')}):"]
        if current.get("subject"):
            parts.append(f"Subject: {current['subject']}")
        parts.append(f"Content: {current['content_text']}")
        if current.get("rating") is not None:
            parts.append(f"Rating: {current['rating']}/5")
        if current.get("platform"):
            parts.append(f"Platform: {current['platform']}")

        msg = HumanMessage(content="\n".join(parts))
        result["messages"] = [msg]

    return result


def finalize_node(state: PipelineState) -> dict:
    """Finalize the current ticket and add to completed list."""
    ticket = state.get("ticket")
    ticket_id = ticket["ticket_id"] if ticket else "UNKNOWN"
    logger.info("Finalized ticket %s", ticket_id)

    return {
        "completed_tickets": [ticket_id],
        "current_agent": "finalize",
        "status": "finalized",
    }


def next_item_node(state: PipelineState) -> dict:
    """Advance to the next feedback item and clear per-item state."""
    new_index = state["current_index"] + 1
    logger.info("Moving to item %d/%d", new_index + 1, state["total_items"])

    return {
        "current_index": new_index,
        "current_agent": "next_item",
        # Clear per-item agentic state to prevent context bloat
        "messages": [],
        "next_agent": "",
        "supervisor_reasoning": "",
    }


# ---------------------------------------------------------------------------
# make_agent_node wrapper (bridges ReAct sub-agents with PipelineState)
# ---------------------------------------------------------------------------

def make_agent_node(
    agent_callable: Callable,
    agent_name: str,
    output_key: str,
    extract_fn: Optional[Callable] = None,
) -> Callable:
    """Wrap a ReAct sub-agent (or legacy node) to bridge with PipelineState.

    For Phase 2 this wraps legacy node functions. In Phases 3-4 it will
    wrap compiled ReAct agent graphs.

    Args:
        agent_callable: The node function or compiled agent to invoke.
        agent_name: Name for logging (e.g., "classifier").
        output_key: State key to write results to (e.g., "classification").
        extract_fn: Optional function to extract structured data from agent output.
    """

    def node_fn(state: PipelineState) -> dict:
        start = time.perf_counter()
        try:
            result = agent_callable(state)
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Log the agent's action
            item = state.get("current_item")
            if item:
                log_processing(
                    agent_name=agent_name,
                    action="process",
                    status="success",
                    feedback_id=item.get("feedback_id"),
                    ticket_id=result.get("ticket", {}).get("ticket_id") if isinstance(result.get("ticket"), dict) else None,
                    input_summary=f"item={item.get('source_id', 'N/A')}",
                    output_summary=f"output_key={output_key}",
                    latency_ms=elapsed_ms,
                    trace_id=state.get("trace_id"),
                )

            # Add an AI message summarizing what the agent did
            summary = _summarize_agent_output(agent_name, result, output_key)
            if summary:
                result.setdefault("messages", [])
                result["messages"] = result.get("messages", []) + [AIMessage(content=summary)]

            return result
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error("Agent %s failed: %s", agent_name, e, exc_info=True)
            item = state.get("current_item")
            if item:
                log_processing(
                    agent_name=agent_name,
                    action="process",
                    status="error",
                    feedback_id=item.get("feedback_id"),
                    error_message=str(e),
                    latency_ms=elapsed_ms,
                    trace_id=state.get("trace_id"),
                )
            return {
                "current_agent": agent_name,
                "status": "error",
                "error_message": f"{agent_name} failed: {e}",
            }

    return node_fn


def _summarize_agent_output(agent_name: str, result: dict, output_key: str) -> str:
    """Create a brief text summary of what the agent produced."""
    data = result.get(output_key)
    if not data:
        return ""

    if agent_name == "classifier" and isinstance(data, dict):
        return (f"[Classifier] Category: {data.get('category')}, "
                f"Confidence: {data.get('confidence')}, "
                f"Reasoning: {data.get('reasoning', '')[:100]}")

    if agent_name in ("bug_analyzer", "feature_extractor") and isinstance(data, dict):
        return f"[{agent_name}] Analysis complete: {json.dumps(data, default=str)[:200]}"

    if agent_name == "ticket_creator" and isinstance(data, dict):
        return (f"[Ticket Creator] Created {data.get('ticket_id', 'N/A')}: "
                f"{data.get('title', 'N/A')[:80]}")

    if agent_name == "quality_critic" and isinstance(data, dict):
        return (f"[Quality Critic] Score: {data.get('score', 'N/A')}, "
                f"Approved: {data.get('approved', 'N/A')}")

    return f"[{agent_name}] Output written to state['{output_key}']"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_pipeline(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    status_callback: Optional[Callable] = None,
) -> StateGraph:
    """Build and compile the agentic feedback processing pipeline.

    Architecture: hybrid supervisor + specialist agents.

    Args:
        api_key: OpenAI API key. Defaults to settings.
        model: Model name. Defaults to settings.openai_model.
        temperature: LLM temperature. Defaults to settings.openai_temperature.
        status_callback: Optional callback for real-time status updates.

    Returns:
        Compiled LangGraph StateGraph.
    """
    llm = ChatOpenAI(
        api_key=api_key or settings.openai_api_key,
        model=model or settings.openai_model,
        temperature=temperature if temperature is not None else settings.openai_temperature,
    )

    # Supervisor uses temperature=0 for consistent routing
    supervisor_llm = ChatOpenAI(
        api_key=api_key or settings.openai_api_key,
        model=model or settings.openai_model,
        temperature=0,
    )

    # Create agent node functions
    classify = create_classify_node(llm)
    bug_analyze = create_bug_analyze_node(llm)
    feature_extract = create_feature_extract_node(llm)
    create_ticket = create_ticket_node(llm)
    quality_review = create_quality_review_node(llm)
    supervisor = create_supervisor_node(supervisor_llm)

    # Wrap agents with make_agent_node for logging and message tracking
    wrapped_classify = make_agent_node(classify, "classifier", "classification")
    wrapped_bug = make_agent_node(bug_analyze, "bug_analyzer", "analysis")
    wrapped_feature = make_agent_node(feature_extract, "feature_extractor", "analysis")
    wrapped_ticket = make_agent_node(create_ticket, "ticket_creator", "ticket")
    wrapped_quality = make_agent_node(quality_review, "quality_critic", "quality_review")

    # Optionally add status callbacks
    if status_callback:
        wrapped_classify = _with_callback(wrapped_classify, status_callback)
        wrapped_bug = _with_callback(wrapped_bug, status_callback)
        wrapped_feature = _with_callback(wrapped_feature, status_callback)
        wrapped_ticket = _with_callback(wrapped_ticket, status_callback)
        wrapped_quality = _with_callback(wrapped_quality, status_callback)
        _ingest = _with_callback(_agentic_ingest_node, status_callback)
        _finalize = _with_callback(finalize_node, status_callback)
        _supervisor = _with_callback(supervisor, status_callback)
    else:
        _ingest = _agentic_ingest_node
        _finalize = finalize_node
        _supervisor = supervisor

    # Build the graph
    workflow = StateGraph(PipelineState)

    # Add nodes
    workflow.add_node("ingest", _ingest)
    workflow.add_node("classify", wrapped_classify)
    workflow.add_node("supervisor", _supervisor)
    workflow.add_node("bug_analyzer", wrapped_bug)
    workflow.add_node("feature_extractor", wrapped_feature)
    workflow.add_node("ticket_creator", wrapped_ticket)
    workflow.add_node("quality_critic", wrapped_quality)
    workflow.add_node("finalize", _finalize)
    workflow.add_node("next_item", next_item_node)

    # --- Edges ---
    # Entry
    workflow.set_entry_point("ingest")

    # Deterministic: ingest → classify
    workflow.add_edge("ingest", "classify")

    # Deterministic: classify → supervisor (first decision point)
    workflow.add_edge("classify", "supervisor")

    # Supervisor routes to: bug_analyzer | feature_extractor | ticket_creator | finalize
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "bug_analyzer": "bug_analyzer",
            "feature_extractor": "feature_extractor",
            "ticket_creator": "ticket_creator",
            "finalize": "finalize",
        },
    )

    # Deterministic: analyzers → ticket_creator
    workflow.add_edge("bug_analyzer", "ticket_creator")
    workflow.add_edge("feature_extractor", "ticket_creator")

    # Deterministic: ticket_creator → quality_critic
    workflow.add_edge("ticket_creator", "quality_critic")

    # Deterministic: quality_critic → supervisor (second decision point)
    workflow.add_edge("quality_critic", "supervisor")

    # Deterministic: finalize → next_item
    workflow.add_edge("finalize", "next_item")

    # Deterministic: next_item → ingest (loop) or END
    workflow.add_conditional_edges(
        "next_item",
        route_next_or_end,
        {
            "ingest": "ingest",
            "end": END,
        },
    )

    # Compile with Langfuse tracing if available
    compiled = workflow.compile()

    langfuse_handler = create_langfuse_handler()
    if langfuse_handler:
        compiled = compiled.with_config({"callbacks": [langfuse_handler]})

    return compiled


def create_initial_state(
    feedback_items: list[dict],
    batch_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> PipelineState:
    """Create the initial pipeline state for a batch of feedback items."""
    return PipelineState(
        batch_id=batch_id or str(uuid.uuid4())[:8],
        trace_id=trace_id or str(uuid.uuid4()),
        feedback_items=feedback_items,
        current_index=0,
        total_items=len(feedback_items),
        current_item=None,
        classification=None,
        analysis=None,
        ticket=None,
        quality_review=None,
        current_agent="",
        status="pending",
        error_message=None,
        revision_count=0,
        completed_tickets=[],
        # Agentic fields
        messages=[],
        next_agent="",
        supervisor_reasoning="",
    )


def _with_callback(node_fn: Callable, callback: Callable) -> Callable:
    """Wrap a node function to call the status callback after execution."""

    def wrapped(state: PipelineState) -> dict:
        result = node_fn(state)
        try:
            callback({
                "agent": result.get("current_agent", ""),
                "status": result.get("status", ""),
                "current_index": state.get("current_index", 0),
                "total_items": state.get("total_items", 0),
                "ticket": result.get("ticket"),
                "classification": result.get("classification") or state.get("classification"),
                "quality_review": result.get("quality_review"),
                "supervisor_reasoning": result.get("supervisor_reasoning", ""),
            })
        except Exception as e:
            logger.warning("Status callback error: %s", e)
        return result

    return wrapped
