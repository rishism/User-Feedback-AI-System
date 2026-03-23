"""SQL helper functions for raw_feedback, tickets, and processing_log tables."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from src.db.database import get_conn


# ---------------------------------------------------------------------------
# raw_feedback helpers
# ---------------------------------------------------------------------------

def insert_feedback(
    source_id: str,
    source_type: str,
    content_text: str,
    *,
    source_file: str | None = None,
    subject: str | None = None,
    sender: str | None = None,
    rating: int | None = None,
    platform: str | None = None,
    priority_hint: str | None = None,
    original_date: str | None = None,
    app_version: str | None = None,
    raw_json: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Insert a feedback row and return its id."""
    _conn = conn or get_conn()
    try:
        cursor = _conn.execute(
            """INSERT OR IGNORE INTO raw_feedback
               (source_id, source_type, source_file, content_text, subject,
                sender, rating, platform, priority_hint, original_date,
                app_version, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_id, source_type, source_file, content_text, subject,
                sender, rating, platform, priority_hint, original_date,
                app_version, raw_json,
            ),
        )
        if conn is None:
            _conn.commit()
        # If INSERT OR IGNORE skipped the row, fetch the existing id
        if cursor.lastrowid == 0:
            row = _conn.execute(
                "SELECT id FROM raw_feedback WHERE source_id = ? AND source_type = ?",
                (source_id, source_type),
            ).fetchone()
            return row["id"]
        return cursor.lastrowid
    finally:
        if conn is None:
            _conn.close()


def update_feedback_status(
    feedback_id: int,
    status: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    _conn = conn or get_conn()
    try:
        _conn.execute(
            "UPDATE raw_feedback SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, feedback_id),
        )
        if conn is None:
            _conn.commit()
    finally:
        if conn is None:
            _conn.close()


def get_feedback_by_id(
    feedback_id: int,
    conn: sqlite3.Connection | None = None,
) -> Optional[dict]:
    _conn = conn or get_conn()
    try:
        row = _conn.execute(
            "SELECT * FROM raw_feedback WHERE id = ?", (feedback_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        if conn is None:
            _conn.close()


def get_all_feedback(
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    _conn = conn or get_conn()
    try:
        if status:
            rows = _conn.execute(
                "SELECT * FROM raw_feedback WHERE status = ? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = _conn.execute(
                "SELECT * FROM raw_feedback ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# tickets helpers
# ---------------------------------------------------------------------------

def generate_ticket_id(conn: sqlite3.Connection | None = None) -> str:
    """Generate the next ticket ID in format TKT-YYYYMMDD-NNN."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"TKT-{today}-"
    _conn = conn or get_conn()
    try:
        row = _conn.execute(
            "SELECT ticket_id FROM tickets WHERE ticket_id LIKE ? ORDER BY ticket_id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
        if row:
            last_num = int(row["ticket_id"].split("-")[-1])
            return f"{prefix}{last_num + 1:03d}"
        return f"{prefix}001"
    finally:
        if conn is None:
            _conn.close()


def insert_ticket(
    ticket_id: str,
    feedback_id: int,
    category: str,
    confidence: float,
    title: str,
    description: str,
    priority: str,
    *,
    severity: str | None = None,
    technical_details: str | None = None,
    feature_details: str | None = None,
    suggested_actions: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Insert a ticket row and return the ticket_id."""
    _conn = conn or get_conn()
    try:
        _conn.execute(
            """INSERT INTO tickets
               (ticket_id, feedback_id, category, confidence, title, description,
                priority, severity, technical_details, feature_details, suggested_actions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticket_id, feedback_id, category, confidence, title, description,
                priority, severity, technical_details, feature_details, suggested_actions,
            ),
        )
        if conn is None:
            _conn.commit()
        return ticket_id
    finally:
        if conn is None:
            _conn.close()


def update_ticket(
    ticket_id: str,
    conn: sqlite3.Connection | None = None,
    **fields,
) -> None:
    """Update ticket fields by ticket_id. Only provided fields are updated."""
    if not fields:
        return
    allowed = {
        "title", "description", "priority", "severity",
        "technical_details", "feature_details", "suggested_actions",
        "quality_score", "quality_notes", "quality_status",
        "revision_count", "manually_edited", "edited_by",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [ticket_id]

    _conn = conn or get_conn()
    try:
        _conn.execute(
            f"UPDATE tickets SET {set_clause}, updated_at = datetime('now') WHERE ticket_id = ?",
            values,
        )
        if conn is None:
            _conn.commit()
    finally:
        if conn is None:
            _conn.close()


def get_tickets(
    category: str | None = None,
    priority: str | None = None,
    quality_status: str | None = None,
    limit: int = 50,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Retrieve tickets with optional filters."""
    _conn = conn or get_conn()
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
        rows = _conn.execute(
            f"SELECT * FROM tickets {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if conn is None:
            _conn.close()


def get_ticket_by_id(
    ticket_id: str,
    conn: sqlite3.Connection | None = None,
) -> Optional[dict]:
    _conn = conn or get_conn()
    try:
        row = _conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        if conn is None:
            _conn.close()


# ---------------------------------------------------------------------------
# processing_log helpers
# ---------------------------------------------------------------------------

def log_processing(
    agent_name: str,
    action: str,
    status: str,
    *,
    feedback_id: int | None = None,
    ticket_id: str | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    error_message: str | None = None,
    latency_ms: float | None = None,
    trace_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    _conn = conn or get_conn()
    try:
        _conn.execute(
            """INSERT INTO processing_log
               (feedback_id, ticket_id, agent_name, action, status,
                input_summary, output_summary, error_message, latency_ms, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                feedback_id, ticket_id, agent_name, action, status,
                input_summary, output_summary, error_message, latency_ms, trace_id,
            ),
        )
        if conn is None:
            _conn.commit()
    finally:
        if conn is None:
            _conn.close()


def get_processing_logs(
    feedback_id: int | None = None,
    limit: int = 100,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    _conn = conn or get_conn()
    try:
        if feedback_id:
            rows = _conn.execute(
                "SELECT * FROM processing_log WHERE feedback_id = ? ORDER BY created_at DESC LIMIT ?",
                (feedback_id, limit),
            ).fetchall()
        else:
            rows = _conn.execute(
                "SELECT * FROM processing_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if conn is None:
            _conn.close()
