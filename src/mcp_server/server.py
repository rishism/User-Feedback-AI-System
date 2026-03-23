"""FastMCP server for ticket management backed by SQLite."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

mcp = FastMCP("Feedback Ticket System")

# Resolve DB path relative to project root
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "db" / "feedback.db"


def _get_conn() -> sqlite3.Connection:
    path = Path(DB_PATH) if not isinstance(DB_PATH, Path) else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _generate_ticket_id(conn: sqlite3.Connection) -> str:
    """Generate next ticket ID: TKT-YYYYMMDD-NNN."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"TKT-{today}-"
    row = conn.execute(
        "SELECT ticket_id FROM tickets WHERE ticket_id LIKE ? ORDER BY ticket_id DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    if row:
        last_num = int(row["ticket_id"].split("-")[-1])
        return f"{prefix}{last_num + 1:03d}"
    return f"{prefix}001"


@mcp.tool
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
    """Create a new ticket from analyzed user feedback.

    Args:
        feedback_id: ID of the raw feedback record
        category: Bug | Feature Request | Praise | Complaint | Spam
        confidence: Classification confidence 0.0-1.0
        title: Ticket title
        description: Ticket description
        priority: Critical | High | Medium | Low
        severity: Bug severity (optional)
        technical_details: JSON string of technical details (optional)
        feature_details: JSON string of feature details (optional)
        suggested_actions: JSON string array of actions (optional)

    Returns:
        JSON with the created ticket_id and status
    """
    conn = _get_conn()
    try:
        ticket_id = _generate_ticket_id(conn)
        conn.execute(
            """INSERT INTO tickets
               (ticket_id, feedback_id, category, confidence, title, description,
                priority, severity, technical_details, feature_details, suggested_actions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticket_id, feedback_id, category, confidence, title, description,
                priority, severity, technical_details, feature_details, suggested_actions,
            ),
        )
        conn.commit()
        return json.dumps({"ticket_id": ticket_id, "status": "created"})
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})
    finally:
        conn.close()


@mcp.tool
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
    """Update an existing ticket's fields.

    Args:
        ticket_id: The ticket ID to update (e.g., 'TKT-20260323-001')
        title: New ticket title (optional)
        description: New description (optional)
        priority: New priority (optional)
        quality_score: Quality critic score 0-10 (optional)
        quality_notes: Quality critic notes (optional)
        quality_status: pending | approved | revision_needed | revised (optional)
        revision_count: Number of revisions (optional)
        manually_edited: Whether ticket was manually edited (optional)

    Returns:
        JSON with update status
    """
    updates = {}
    for field_name, value in [
        ("title", title), ("description", description), ("priority", priority),
        ("quality_score", quality_score), ("quality_notes", quality_notes),
        ("quality_status", quality_status), ("revision_count", revision_count),
        ("manually_edited", 1 if manually_edited else None if manually_edited is None else 0),
    ]:
        if value is not None:
            updates[field_name] = value

    if not updates:
        return json.dumps({"error": "No fields to update", "status": "failed"})

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [ticket_id]

    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"UPDATE tickets SET {set_clause}, updated_at = datetime('now') WHERE ticket_id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return json.dumps({"error": f"Ticket {ticket_id} not found", "status": "failed"})
        return json.dumps({"ticket_id": ticket_id, "status": "updated"})
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})
    finally:
        conn.close()


@mcp.tool
def get_tickets(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    quality_status: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Retrieve tickets with optional filters.

    Args:
        category: Filter by category - Bug, Feature Request, Praise, Complaint, Spam (optional)
        priority: Filter by priority - Critical, High, Medium, Low (optional)
        quality_status: Filter by review status - pending, approved, revision_needed (optional)
        limit: Max number of tickets to return (default 50)

    Returns:
        JSON array of ticket records
    """
    conn = _get_conn()
    try:
        conditions = []
        params: list = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if quality_status:
            conditions.append("quality_status = ?")
            params.append(quality_status)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM tickets {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        tickets = [dict(r) for r in rows]
        return json.dumps(tickets, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "status": "failed"})
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
