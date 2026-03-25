"""Tests for the MCP server tools (direct function calls, no MCP protocol)."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.db.database import init_db


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO raw_feedback (source_id, source_type, content_text) VALUES (?, ?, ?)",
        ("R001", "app_store_review", "Test feedback"),
    )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


@pytest.fixture(autouse=True)
def patch_db_path(db_path):
    """Patch DB_PATH with a Path object so _get_conn works correctly."""
    with patch("src.mcp_server.server.DB_PATH", Path(db_path)):
        yield


class TestMCPServerTools:
    def test_create_ticket(self):
        from src.mcp_server.server import create_ticket

        result = json.loads(create_ticket(
            feedback_id=1,
            category="Bug",
            confidence=0.95,
            title="Test Bug",
            description="Test description",
            priority="High",
        ))

        assert result["status"] == "created"
        assert result["ticket_id"].startswith("TKT-")

    def test_get_tickets(self):
        from src.mcp_server.server import create_ticket, get_tickets

        create_ticket(1, "Bug", 0.9, "Bug 1", "Desc", "High")
        create_ticket(1, "Feature Request", 0.8, "Feature 1", "Desc", "Medium")

        all_tickets = json.loads(get_tickets())
        assert len(all_tickets) == 2

        bugs = json.loads(get_tickets(category="Bug"))
        assert len(bugs) == 1
        assert bugs[0]["category"] == "Bug"

    def test_update_ticket(self):
        from src.mcp_server.server import create_ticket, update_ticket

        result = json.loads(create_ticket(1, "Bug", 0.9, "Old Title", "Desc", "Medium"))
        ticket_id = result["ticket_id"]

        update_result = json.loads(update_ticket(ticket_id, title="New Title", quality_score=8.5))
        assert update_result["status"] == "updated"

    def test_update_nonexistent_ticket(self):
        from src.mcp_server.server import update_ticket

        result = json.loads(update_ticket("TKT-99999999-999", title="No ticket"))
        assert result["status"] == "failed"
