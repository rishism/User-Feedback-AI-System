"""SQLite database initialization and connection management."""

import sqlite3
from pathlib import Path

from src.config import settings

_RAW_FEEDBACK_SQL = """
CREATE TABLE IF NOT EXISTS raw_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_file     TEXT,
    content_text    TEXT NOT NULL,
    subject         TEXT,
    sender          TEXT,
    rating          INTEGER,
    platform        TEXT,
    priority_hint   TEXT,
    original_date   TEXT,
    app_version     TEXT,
    raw_json        TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, source_type)
);
"""

_TICKETS_SQL = """
CREATE TABLE IF NOT EXISTS tickets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id           TEXT NOT NULL UNIQUE,
    feedback_id         INTEGER NOT NULL,
    category            TEXT NOT NULL,
    confidence          REAL NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    priority            TEXT NOT NULL,
    severity            TEXT,
    technical_details   TEXT,
    feature_details     TEXT,
    suggested_actions   TEXT,
    quality_score       REAL,
    quality_notes       TEXT,
    quality_status      TEXT DEFAULT 'pending',
    revision_count      INTEGER DEFAULT 0,
    manually_edited     INTEGER DEFAULT 0,
    edited_by           TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (feedback_id) REFERENCES raw_feedback(id)
);
"""

_PROCESSING_LOG_SQL = """
CREATE TABLE IF NOT EXISTS processing_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id     INTEGER,
    ticket_id       TEXT,
    agent_name      TEXT NOT NULL,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL,
    input_summary   TEXT,
    output_summary  TEXT,
    error_message   TEXT,
    latency_ms      REAL,
    trace_id        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db_path() -> str:
    return settings.db_path


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Return a connection with Row factory enabled."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create all tables if they don't exist."""
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(path)
    try:
        conn.execute(_RAW_FEEDBACK_SQL)
        conn.execute(_TICKETS_SQL)
        conn.execute(_PROCESSING_LOG_SQL)
        conn.commit()
    finally:
        conn.close()
