"""MCP tool wrappers for the agentic pipeline.

Provides LangChain @tool functions that call the MCP server (src/mcp_server/server.py)
via SSE transport. The MCP server runs as a background subprocess on localhost:8765,
auto-started on the first tool call and reused for all subsequent calls.
"""

import asyncio
import atexit
import json
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from fastmcp import Client
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

SERVER_PATH = str(
    Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
)

MCP_HOST = "127.0.0.1"
MCP_PORT = 8765
MCP_SERVER_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"

# ---------------------------------------------------------------------------
# MCP server process management
# ---------------------------------------------------------------------------

_server_process: subprocess.Popen | None = None
_server_lock = threading.Lock()


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def _ensure_server_running() -> None:
    """Start the MCP SSE server if not already running.

    Auto-starts the server as a background subprocess on first call.
    Reuses an existing server if one is already listening on the port
    (e.g., from a previous Streamlit session or manual start).
    """
    global _server_process

    # Fast path: server already reachable
    if _is_port_open(MCP_HOST, MCP_PORT):
        return

    with _server_lock:
        # Double-check after acquiring lock
        if _is_port_open(MCP_HOST, MCP_PORT):
            return

        logger.info("Starting MCP SSE server on %s:%d ...", MCP_HOST, MCP_PORT)
        _server_process = subprocess.Popen(
            [sys.executable, SERVER_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait up to 5 seconds for the server to become ready
        for _ in range(50):
            if _server_process.poll() is not None:
                stderr = _server_process.stderr.read().decode() if _server_process.stderr else ""
                raise RuntimeError(f"MCP server exited unexpectedly: {stderr[:500]}")
            if _is_port_open(MCP_HOST, MCP_PORT):
                logger.info("MCP SSE server ready (pid=%d)", _server_process.pid)
                return
            time.sleep(0.1)

        raise RuntimeError(f"MCP server did not start within 5s (pid={_server_process.pid})")


def _shutdown_server() -> None:
    """Terminate the MCP server subprocess on process exit."""
    global _server_process
    if _server_process and _server_process.poll() is None:
        logger.info("Shutting down MCP server (pid=%d)", _server_process.pid)
        _server_process.terminate()
        try:
            _server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None


atexit.register(_shutdown_server)


# ---------------------------------------------------------------------------
# Core MCP call helper (SSE transport — stateless per request)
# ---------------------------------------------------------------------------

def _call_mcp_tool(tool_name: str, kwargs: dict) -> str:
    """Call an MCP tool via the SSE-based MCP server.

    Each call creates a fresh Client connection. With SSE transport,
    connections are stateless HTTP requests — no persistent async state,
    so asyncio.run() is safe (no event loop lifecycle issues).
    """
    _ensure_server_running()

    async def _invoke():
        async with Client(MCP_SERVER_URL) as client:
            result = await client.call_tool(tool_name, kwargs)
            if result.content:
                block = result.content[0]
                return block.text if hasattr(block, "text") else str(block)
            return json.dumps({"error": "No result returned", "status": "failed"})

    try:
        return asyncio.run(_invoke())
    except Exception as e:
        logger.error("MCP tool %s failed: %s", tool_name, e, exc_info=True)
        return json.dumps({"error": str(e), "status": "failed"})


# ---------------------------------------------------------------------------
# LangChain @tool wrappers (used by ReAct agents via bind_tools)
# ---------------------------------------------------------------------------

@tool
def create_ticket(
    feedback_id: int,
    category: str,
    confidence: float,
    title: str,
    description: str,
    priority: str,
    severity: Optional[str] = None,
    technical_details: Optional[str] = None,
    feature_details: Optional[str] = None,
    suggested_actions: Optional[str] = None,
) -> str:
    """Create a new ticket from analyzed user feedback via MCP.

    You MUST call this tool to persist the ticket to the database.

    Args:
        feedback_id: ID of the raw feedback record.
        category: Bug | Feature Request | Praise | Complaint | Spam.
        confidence: Classification confidence 0.0-1.0.
        title: Ticket title — clear, actionable, under 80 chars, prefixed with [Category].
        description: Full ticket description with structured sections.
        priority: Critical | High | Medium | Low.
        severity: Bug severity (optional).
        technical_details: JSON string of technical details (optional).
        feature_details: JSON string of feature details (optional).
        suggested_actions: JSON array string of actions (optional).

    Returns:
        JSON with ticket_id and status.
    """
    kwargs = {
        "feedback_id": feedback_id,
        "category": category,
        "confidence": confidence,
        "title": title,
        "description": description,
        "priority": priority,
    }
    if severity is not None:
        kwargs["severity"] = severity
    if technical_details is not None:
        kwargs["technical_details"] = technical_details
    if feature_details is not None:
        kwargs["feature_details"] = feature_details
    if suggested_actions is not None:
        kwargs["suggested_actions"] = suggested_actions

    return _call_mcp_tool("create_ticket", kwargs)


@tool
def update_ticket(
    ticket_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    quality_score: Optional[float] = None,
    quality_notes: Optional[str] = None,
    quality_status: Optional[str] = None,
    revision_count: Optional[int] = None,
    manually_edited: Optional[bool] = None,
) -> str:
    """Update an existing ticket's fields via MCP.

    Use this to write quality review results or edit ticket content.

    Args:
        ticket_id: The ticket ID (e.g., 'TKT-20260324-001').
        title: New ticket title (optional).
        description: New description (optional).
        priority: New priority (optional).
        quality_score: Quality score 0-10 (optional).
        quality_notes: Quality review notes (optional).
        quality_status: pending | approved | revision_needed | revised (optional).
        revision_count: Number of revisions (optional).
        manually_edited: Whether manually edited (optional).

    Returns:
        JSON with update status.
    """
    kwargs = {"ticket_id": ticket_id}
    for key, val in [
        ("title", title), ("description", description), ("priority", priority),
        ("quality_score", quality_score), ("quality_notes", quality_notes),
        ("quality_status", quality_status), ("revision_count", revision_count),
        ("manually_edited", manually_edited),
    ]:
        if val is not None:
            kwargs[key] = val

    return _call_mcp_tool("update_ticket", kwargs)


@tool
def get_tickets(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    quality_status: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Retrieve tickets from the database via MCP with optional filters.

    Use this to check for duplicate tickets or review existing tickets.

    Args:
        category: Filter by category (optional).
        priority: Filter by priority (optional).
        quality_status: Filter by review status (optional).
        limit: Max tickets to return (default 50).

    Returns:
        JSON array of ticket records.
    """
    kwargs: dict = {}
    if category is not None:
        kwargs["category"] = category
    if priority is not None:
        kwargs["priority"] = priority
    if quality_status is not None:
        kwargs["quality_status"] = quality_status
    kwargs["limit"] = limit

    return _call_mcp_tool("get_tickets", kwargs)


# All MCP tools for convenient import
ALL_MCP_TOOLS = [create_ticket, update_ticket, get_tickets]
