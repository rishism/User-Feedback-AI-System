# MCP Server

## Overview

The system includes a **FastMCP server** that exposes ticket management operations as MCP tools. This provides a standardized, tool-based interface for creating, updating, and querying tickets — used as an alternative to direct database access by the Ticket Creator agent.

All server code is in `src/mcp_server/server.py`.

## Server Setup

```python
# server.py:9-14
from fastmcp import FastMCP
mcp = FastMCP("Feedback Ticket System")

# Database path resolved relative to project root
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "db" / "feedback.db"
```

The server creates its own database connections (separate from the main application's `get_conn()`) using `_get_conn()` (`server.py:17-23`), which enables Row factory and foreign key enforcement.

## Transport

The server runs over **stdio transport** (`server.py:197-198`):

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

This means the server is spawned as a **subprocess** by clients and communicates via standard input/output — no network ports needed. The Ticket Creator agent spawns it this way when `use_mcp=True`.

---

## Tools

### `create_ticket` (`server.py:40-88`)

Creates a new ticket from analyzed user feedback.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `feedback_id` | `int` | Yes | ID of the raw_feedback record |
| `category` | `str` | Yes | `Bug` \| `Feature Request` \| `Praise` \| `Complaint` \| `Spam` |
| `confidence` | `float` | Yes | Classification confidence 0.0-1.0 |
| `title` | `str` | Yes | Ticket title |
| `description` | `str` | Yes | Ticket description |
| `priority` | `str` | Yes | `Critical` \| `High` \| `Medium` \| `Low` |
| `severity` | `str` | No | Bug severity (e.g., `Critical`, `Major`) |
| `technical_details` | `str` | No | JSON string of bug analysis |
| `feature_details` | `str` | No | JSON string of feature analysis |
| `suggested_actions` | `str` | No | JSON array string of recommended actions |

**Returns:**

Success:
```json
{"ticket_id": "TKT-20260323-001", "status": "created"}
```

Failure:
```json
{"error": "UNIQUE constraint failed: tickets.ticket_id", "status": "failed"}
```

**Behavior:**
- Generates a ticket ID via `_generate_ticket_id()` (`server.py:26-37`)
- Inserts into the `tickets` table
- Commits the transaction

### `update_ticket` (`server.py:91-148`)

Updates an existing ticket's fields.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `ticket_id` | `str` | Yes | Ticket ID to update (e.g., `TKT-20260323-001`) |
| `title` | `str` | No | New title |
| `description` | `str` | No | New description |
| `priority` | `str` | No | New priority |
| `quality_score` | `float` | No | Quality critic score 0-10 |
| `quality_notes` | `str` | No | Quality critic notes |
| `quality_status` | `str` | No | `pending` \| `approved` \| `revision_needed` \| `revised` |
| `revision_count` | `int` | No | Number of revisions |
| `manually_edited` | `bool` | No | Whether manually edited |

**Returns:**

Success:
```json
{"ticket_id": "TKT-20260323-001", "status": "updated"}
```

No fields provided:
```json
{"error": "No fields to update", "status": "failed"}
```

Ticket not found:
```json
{"error": "Ticket TKT-20260323-001 not found", "status": "failed"}
```

**Behavior:**
- Only updates non-`None` fields
- Also sets `updated_at` to current time (`server.py:138`)
- Checks `cursor.rowcount == 0` to detect non-existent tickets (`server.py:142`)

### `get_tickets` (`server.py:151-194`)

Retrieves tickets with optional filters.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `category` | `str` | No | `None` | Filter by category |
| `priority` | `str` | No | `None` | Filter by priority |
| `quality_status` | `str` | No | `None` | Filter by review status |
| `limit` | `int` | No | `50` | Maximum results |

**Returns:**

Success (JSON array):
```json
[
  {
    "id": 1,
    "ticket_id": "TKT-20260323-001",
    "category": "Bug",
    "title": "[Bug] App crashes on login",
    "priority": "High",
    "quality_score": 8.5,
    "quality_status": "approved",
    ...
  }
]
```

**Behavior:**
- Builds a dynamic `WHERE` clause from provided filters (`server.py:171-183`)
- Orders by `created_at DESC`
- Uses `json.dumps(tickets, default=str)` for serialization (`server.py:190`)

---

## Ticket ID Generation

`_generate_ticket_id(conn)` (`server.py:26-37`) generates IDs in the format `TKT-YYYYMMDD-NNN`:

1. Gets today's date in UTC: `TKT-20260323-`
2. Queries the last ticket with today's prefix (ordered DESC)
3. If found: extracts the last number, increments by 1, zero-pads to 3 digits
4. If none found: starts at `001`

Example sequence: `TKT-20260323-001`, `TKT-20260323-002`, ..., `TKT-20260323-999`

---

## Client Integration

### `_create_via_mcp()` in Ticket Creator (`ticket_creator.py:196-216`)

The Ticket Creator agent connects as an MCP client when `use_mcp=True`:

```python
def _create_via_mcp(**kwargs) -> str:
    from fastmcp import Client

    server_path = str(
        Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
    )

    async def _call():
        async with Client(server_path) as client:
            result = await client.call_tool("create_ticket", kwargs)
            data = json.loads(result[0].text)
            return data.get("ticket_id", "UNKNOWN")

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, _call()).result()
```

Key details:
- The server path is resolved relative to the `ticket_creator.py` file location
- `fastmcp.Client` spawns the server as a subprocess with stdio transport
- The async call is bridged to sync code via `ThreadPoolExecutor` + `asyncio.run`
- Only the `ticket_id` is extracted from the response

### Enabling MCP in the Pipeline (`workflow.py:115`)

```python
create_ticket = create_ticket_node(llm, use_mcp=use_mcp)
```

The `use_mcp` flag is passed through `build_pipeline(use_mcp=True)` (`workflow.py:90`).

---

## Running Standalone

The MCP server can be run independently for testing:

```bash
python -m src.mcp_server.server
```

This starts the server listening on stdio. You can connect to it using any MCP-compatible client.

---

## Testing

Tests are in `tests/test_mcp_server.py`. They patch `DB_PATH` with a temporary SQLite database to test all three tools in isolation:

- `create_ticket` — creates and verifies a ticket
- `get_tickets` — retrieves created tickets with filters
- `update_ticket` — updates fields and verifies changes
- `update_nonexistent_ticket` — verifies error handling for missing tickets

---

## Related Documentation

- [Database Schema](database_schema.md) — Underlying tables the server reads/writes
- [Agent Design](agent_design.md#5-ticket-creator) — How the pipeline uses MCP
- [Setup and Usage](setup_and_usage.md) — Running the server
