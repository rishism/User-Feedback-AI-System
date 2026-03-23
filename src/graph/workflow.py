"""LangGraph pipeline: StateGraph with conditional edges for feedback processing."""

import logging
import uuid
from typing import Callable, Optional

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from src.agents.bug_analyzer import create_bug_analyze_node
from src.agents.classifier import create_classify_node
from src.agents.csv_agent import ingest_node
from src.agents.feature_extractor import create_feature_extract_node
from src.agents.quality_critic import create_quality_review_node
from src.agents.ticket_creator import create_ticket_node
from src.config import settings
from src.models.state import PipelineState
from src.observability.tracing import create_langfuse_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_classification(state: PipelineState) -> str:
    """Route based on classification category."""
    category = state["classification"]["category"]
    if category == "Bug":
        return "bug_analyze"
    elif category == "Feature Request":
        return "feature_extract"
    else:
        # Praise, Complaint, Spam → skip analysis, go straight to ticket creation
        return "create_ticket"


def route_after_review(state: PipelineState) -> str:
    """Route based on quality review result."""
    review = state["quality_review"]
    if review["approved"] or state["revision_count"] >= settings.max_revision_count:
        return "finalize"
    return "create_ticket"


def route_next_or_end(state: PipelineState) -> str:
    """Route to next item or end the pipeline."""
    if state["current_index"] < state["total_items"]:
        return "ingest"
    return "end"


# ---------------------------------------------------------------------------
# Helper nodes
# ---------------------------------------------------------------------------

def finalize_node(state: PipelineState) -> dict:
    """Finalize the current ticket and add to completed list."""
    ticket = state["ticket"]
    ticket_id = ticket["ticket_id"] if ticket else "UNKNOWN"
    logger.info(f"Finalized ticket {ticket_id}")

    return {
        "completed_tickets": [ticket_id],
        "current_agent": "finalize",
        "status": "finalized",
    }


def next_item_node(state: PipelineState) -> dict:
    """Advance to the next feedback item."""
    new_index = state["current_index"] + 1
    logger.info(f"Moving to item {new_index + 1}/{state['total_items']}")

    return {
        "current_index": new_index,
        "current_agent": "next_item",
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_pipeline(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    use_mcp: bool = False,
    status_callback: Optional[Callable] = None,
) -> StateGraph:
    """Build and compile the feedback processing pipeline.

    Args:
        api_key: OpenAI API key. Defaults to settings.
        model: Model name. Defaults to settings.openai_model.
        temperature: LLM temperature. Defaults to settings.openai_temperature.
        use_mcp: If True, create tickets via MCP server instead of direct DB.
        status_callback: Optional callback for real-time status updates.

    Returns:
        Compiled LangGraph StateGraph.
    """
    llm = ChatOpenAI(
        api_key=api_key or settings.openai_api_key,
        model=model or settings.openai_model,
        temperature=temperature if temperature is not None else settings.openai_temperature,
    )

    # Create agent node functions bound to the LLM
    classify = create_classify_node(llm)
    bug_analyze = create_bug_analyze_node(llm)
    feature_extract = create_feature_extract_node(llm)
    create_ticket = create_ticket_node(llm, use_mcp=use_mcp)
    quality_review = create_quality_review_node(llm)

    # Optionally wrap nodes with status callback for Streamlit
    if status_callback:
        classify = _with_callback(classify, status_callback)
        bug_analyze = _with_callback(bug_analyze, status_callback)
        feature_extract = _with_callback(feature_extract, status_callback)
        create_ticket = _with_callback(create_ticket, status_callback)
        quality_review = _with_callback(quality_review, status_callback)
        _ingest = _with_callback(ingest_node, status_callback)
        _finalize = _with_callback(finalize_node, status_callback)
    else:
        _ingest = ingest_node
        _finalize = finalize_node

    # Build the graph
    workflow = StateGraph(PipelineState)

    # Add nodes
    workflow.add_node("ingest", _ingest)
    workflow.add_node("classify", classify)
    workflow.add_node("bug_analyze", bug_analyze)
    workflow.add_node("feature_extract", feature_extract)
    workflow.add_node("create_ticket", create_ticket)
    workflow.add_node("quality_review", quality_review)
    workflow.add_node("finalize", _finalize)
    workflow.add_node("next_item", next_item_node)

    # Set entry point
    workflow.set_entry_point("ingest")

    # Add edges
    workflow.add_edge("ingest", "classify")

    # Conditional: classify → bug_analyze | feature_extract | create_ticket
    workflow.add_conditional_edges(
        "classify",
        route_after_classification,
        {
            "bug_analyze": "bug_analyze",
            "feature_extract": "feature_extract",
            "create_ticket": "create_ticket",
        },
    )

    workflow.add_edge("bug_analyze", "create_ticket")
    workflow.add_edge("feature_extract", "create_ticket")
    workflow.add_edge("create_ticket", "quality_review")

    # Conditional: quality_review → finalize | create_ticket (revision)
    workflow.add_conditional_edges(
        "quality_review",
        route_after_review,
        {
            "finalize": "finalize",
            "create_ticket": "create_ticket",
        },
    )

    workflow.add_edge("finalize", "next_item")

    # Conditional: next_item → ingest (more items) | END
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
            })
        except Exception as e:
            logger.warning(f"Status callback error: {e}")
        return result

    return wrapped
