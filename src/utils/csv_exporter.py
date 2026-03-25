"""CSV export utilities for generating output files from database tables."""

import csv
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from src.db.database import get_conn

# Default output directory relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "data" / "output"


def export_generated_tickets(
    output_dir: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> Path:
    """Export all tickets from the database to generated_tickets.csv."""
    out = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / "generated_tickets.csv"

    _conn = conn or get_conn()
    try:
        rows = _conn.execute(
            """SELECT ticket_id, feedback_id, category, confidence, title,
                      description, priority, severity, technical_details,
                      feature_details, suggested_actions, quality_score,
                      quality_notes, quality_status, revision_count,
                      created_at, updated_at
               FROM tickets ORDER BY created_at DESC"""
        ).fetchall()

        columns = [
            "ticket_id", "feedback_id", "category", "confidence", "title",
            "description", "priority", "severity", "technical_details",
            "feature_details", "suggested_actions", "quality_score",
            "quality_notes", "quality_status", "revision_count",
            "created_at", "updated_at",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        return filepath
    finally:
        if conn is None:
            _conn.close()


def export_processing_log(
    output_dir: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> Path:
    """Export all processing log entries to processing_log.csv."""
    out = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / "processing_log.csv"

    _conn = conn or get_conn()
    try:
        rows = _conn.execute(
            """SELECT feedback_id, ticket_id, agent_name, action, status,
                      input_summary, output_summary, error_message,
                      latency_ms, trace_id, created_at
               FROM processing_log ORDER BY created_at DESC"""
        ).fetchall()

        columns = [
            "feedback_id", "ticket_id", "agent_name", "action", "status",
            "input_summary", "output_summary", "error_message",
            "latency_ms", "trace_id", "created_at",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row))

        return filepath
    finally:
        if conn is None:
            _conn.close()


def export_metrics(
    output_dir: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> Path:
    """Export aggregated metrics to metrics.csv."""
    out = Path(output_dir) if output_dir else _DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / "metrics.csv"

    df = export_metrics_to_dataframe(conn=conn)

    df.to_csv(filepath, index=False)
    return filepath


def export_metrics_to_dataframe(
    conn: sqlite3.Connection | None = None,
) -> pd.DataFrame:
    """Build a metrics DataFrame from aggregated database queries."""
    _conn = conn or get_conn()
    try:
        metrics = []

        # Summary metrics
        total_feedback = _conn.execute("SELECT COUNT(*) FROM raw_feedback").fetchone()[0]
        metrics.append(("total_feedback_processed", total_feedback, ""))

        total_tickets = _conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        metrics.append(("total_tickets_created", total_tickets, ""))

        avg_quality = _conn.execute(
            "SELECT AVG(quality_score) FROM tickets WHERE quality_score IS NOT NULL"
        ).fetchone()[0]
        metrics.append(("avg_quality_score", f"{avg_quality:.2f}" if avg_quality is not None else "N/A", ""))

        approved = _conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE quality_status = 'approved'"
        ).fetchone()[0]
        metrics.append(("tickets_approved", approved, ""))

        revision_needed = _conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE quality_status = 'revision_needed'"
        ).fetchone()[0]
        metrics.append(("tickets_revision_needed", revision_needed, ""))

        error_count = _conn.execute(
            "SELECT COUNT(*) FROM processing_log WHERE status = 'error'"
        ).fetchone()[0]
        metrics.append(("error_count", error_count, ""))

        avg_latency = _conn.execute(
            "SELECT AVG(latency_ms) FROM processing_log WHERE latency_ms IS NOT NULL"
        ).fetchone()[0]
        metrics.append(("avg_latency_ms", f"{avg_latency:.2f}" if avg_latency is not None else "N/A", ""))

        # Per-category counts
        cat_rows = _conn.execute(
            "SELECT category, COUNT(*) as count FROM tickets GROUP BY category"
        ).fetchall()
        for row in cat_rows:
            metrics.append((f"category_{row['category'].lower().replace(' ', '_')}", row["count"], row["category"]))

        # Per-agent average latency
        agent_rows = _conn.execute(
            "SELECT agent_name, AVG(latency_ms) as avg_ms FROM processing_log "
            "WHERE latency_ms IS NOT NULL GROUP BY agent_name"
        ).fetchall()
        for row in agent_rows:
            metrics.append((f"avg_latency_{row['agent_name']}", f"{row['avg_ms']:.2f}", row["agent_name"]))

        return pd.DataFrame(metrics, columns=["metric_name", "metric_value", "details"])
    finally:
        if conn is None:
            _conn.close()


def export_all_csvs(
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Export all three CSV files and return a dict of {name: path}."""
    conn = get_conn()
    try:
        tickets_path = export_generated_tickets(output_dir=output_dir, conn=conn)
        log_path = export_processing_log(output_dir=output_dir, conn=conn)
        metrics_path = export_metrics(output_dir=output_dir, conn=conn)
        return {
            "generated_tickets": tickets_path,
            "processing_log": log_path,
            "metrics": metrics_path,
        }
    finally:
        conn.close()
