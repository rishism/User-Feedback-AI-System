"""Tests for database initialization and query helpers."""

import os
import tempfile

import pytest

from src.db.database import get_conn, init_db
from src.db.queries import (
    generate_ticket_id,
    get_all_feedback,
    get_feedback_by_id,
    get_tickets,
    insert_feedback,
    insert_ticket,
    log_processing,
    update_feedback_status,
    update_ticket,
)


@pytest.fixture
def db_path():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def conn(db_path):
    """Get a connection to the test database."""
    connection = get_conn(db_path)
    yield connection
    connection.close()


class TestInitDb:
    def test_creates_tables(self, conn):
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "raw_feedback" in table_names
        assert "tickets" in table_names
        assert "processing_log" in table_names

    def test_idempotent(self, db_path):
        """init_db can be called multiple times without error."""
        init_db(db_path)
        init_db(db_path)


class TestFeedbackQueries:
    def test_insert_and_get(self, conn):
        fid = insert_feedback(
            "R001", "app_store_review", "App crashes",
            rating=1, platform="Google Play", conn=conn,
        )
        conn.commit()
        assert fid > 0

        feedback = get_feedback_by_id(fid, conn=conn)
        assert feedback is not None
        assert feedback["source_id"] == "R001"
        assert feedback["content_text"] == "App crashes"
        assert feedback["rating"] == 1

    def test_unique_constraint(self, conn):
        """Inserting same source_id + source_type returns existing id."""
        id1 = insert_feedback("R001", "app_store_review", "First", conn=conn)
        conn.commit()
        id2 = insert_feedback("R001", "app_store_review", "Duplicate", conn=conn)
        conn.commit()
        assert id1 == id2

    def test_update_status(self, conn):
        fid = insert_feedback("R002", "support_email", "Bug report", conn=conn)
        conn.commit()
        update_feedback_status(fid, "classified", conn=conn)
        conn.commit()

        feedback = get_feedback_by_id(fid, conn=conn)
        assert feedback["status"] == "classified"

    def test_get_all_with_filter(self, conn):
        insert_feedback("R003", "app_store_review", "Review 1", conn=conn)
        conn.commit()
        fid2 = insert_feedback("R004", "app_store_review", "Review 2", conn=conn)
        conn.commit()
        update_feedback_status(fid2, "classified", conn=conn)
        conn.commit()

        pending = get_all_feedback(status="pending", conn=conn)
        assert len(pending) == 1

        all_items = get_all_feedback(conn=conn)
        assert len(all_items) == 2


class TestTicketQueries:
    def test_generate_ticket_id(self, conn):
        tid = generate_ticket_id(conn=conn)
        assert tid.startswith("TKT-")
        assert tid.endswith("-001")

    def test_insert_and_get_ticket(self, conn):
        fid = insert_feedback("R010", "app_store_review", "Test", conn=conn)
        conn.commit()

        tid = insert_ticket(
            "TKT-20260323-001", fid, "Bug", 0.9,
            "Test Bug", "Description", "High", conn=conn,
        )
        conn.commit()
        assert tid == "TKT-20260323-001"

        tickets = get_tickets(category="Bug", conn=conn)
        assert len(tickets) == 1
        assert tickets[0]["title"] == "Test Bug"

    def test_update_ticket(self, conn):
        fid = insert_feedback("R011", "app_store_review", "Test", conn=conn)
        conn.commit()
        insert_ticket(
            "TKT-20260323-002", fid, "Bug", 0.8,
            "Old Title", "Old Desc", "Medium", conn=conn,
        )
        conn.commit()

        update_ticket("TKT-20260323-002", conn=conn, title="New Title", quality_score=8.5)
        conn.commit()

        from src.db.queries import get_ticket_by_id
        ticket = get_ticket_by_id("TKT-20260323-002", conn=conn)
        assert ticket["title"] == "New Title"
        assert ticket["quality_score"] == 8.5


class TestProcessingLog:
    def test_log_processing(self, conn):
        log_processing(
            agent_name="classifier",
            action="classify",
            status="success",
            feedback_id=1,
            latency_ms=150.5,
            conn=conn,
        )
        conn.commit()

        from src.db.queries import get_processing_logs
        logs = get_processing_logs(feedback_id=1, conn=conn)
        assert len(logs) == 1
        assert logs[0]["agent_name"] == "classifier"
        assert logs[0]["latency_ms"] == 150.5
