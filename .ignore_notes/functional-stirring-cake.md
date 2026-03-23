# Implementation Plan: Intelligent User Feedback Analysis & Action System

## Context

A B2C mobile app company receives 15-30 pieces of daily user feedback across app stores and support emails. Manual triaging takes 1-2 hours/day and is inconsistent. This project builds a **multi-agent AI system** that automates feedback ingestion, classification, analysis, ticket creation, and quality review — with a Streamlit UI and full Langfuse observability.

---

## Tech Stack

| Component | Choice |
|---|---|
| Language | Python 3.12 |
| Agent Framework | LangChain + LangGraph |
| LLM | OpenAI GPT (model: `gpt-5.4`) via `langchain-openai` |
| Ticket System | FastMCP (Python `mcp` SDK) → SQLite |
| Database | SQLite |
| UI | Streamlit (real-time agent status) |
| Observability | Langfuse |
| Config | pydantic-settings + `.env` |

---

## Project Structure

```
User_Feedback_AI_system/
├── data/
│   ├── mock/
│   │   ├── app_store_reviews.csv
│   │   ├── support_emails.csv
│   │   └── expected_classifications.csv
│   └── db/                              # SQLite DB created at runtime
├── src/
│   ├── __init__.py
│   ├── config.py                        # pydantic-settings: API keys, thresholds
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py                     # LangGraph PipelineState TypedDict
│   │   └── schemas.py                   # Pydantic models for data validation
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py                  # SQLite init_db(), get_conn()
│   │   └── queries.py                   # SQL helper functions
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── csv_agent.py                 # Parse CSV, store in SQLite
│   │   ├── classifier.py               # LLM-based 5-category classification
│   │   ├── bug_analyzer.py             # Extract technical details for bugs
│   │   ├── feature_extractor.py        # Extract feature details for requests
│   │   ├── ticket_creator.py           # Create tickets via MCP tool
│   │   └── quality_critic.py           # Review tickets, approve/reject
│   ├── graph/
│   │   ├── __init__.py
│   │   └── workflow.py                  # LangGraph StateGraph with conditional edges
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   └── server.py                    # FastMCP server: create/update/get tickets
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── tracing.py                   # Langfuse client, trace/span helpers
│   │   └── metrics.py                   # Processing metrics tracking
│   └── utils/
│       ├── __init__.py
│       └── csv_parser.py               # CSV reading/validation utilities
├── streamlit_app/
│   ├── app.py                           # Main entry point
│   └── pages/
│       ├── 1_Upload_and_Process.py      # CSV upload, manual input, real-time status
│       ├── 2_Dashboard.py               # Ticket list, details, manual override
│       ├── 3_Analytics.py               # Charts, metrics, classification accuracy
│       └── 4_Configuration.py           # Thresholds, API key status, settings
├── tests/
│   ├── __init__.py
│   ├── test_csv_agent.py
│   ├── test_classifier.py
│   ├── test_bug_analyzer.py
│   ├── test_feature_extractor.py
│   ├── test_ticket_creator.py
│   ├── test_quality_critic.py
│   ├── test_graph_workflow.py
│   ├── test_mcp_server.py
│   └── test_database.py
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Implementation Order (9 Phases)

### Phase 1 — Foundation
1. `pyproject.toml` + `requirements.txt` (dependencies)
2. `.env.example` + `.gitignore`
3. `src/config.py` — pydantic-settings loading env vars
4. `src/models/schemas.py` — Pydantic models for FeedbackItem, TicketData, ClassificationResult, etc.
5. `src/models/state.py` — LangGraph `PipelineState` TypedDict

### Phase 2 — Database
6. `src/db/database.py` — SQLite init_db(), get_conn(), table creation
7. `src/db/queries.py` — insert/query/update helpers

### Phase 3 — Mock Data
8. `data/mock/app_store_reviews.csv` — 20+ rows covering all 5 categories
9. `data/mock/support_emails.csv` — 15+ rows
10. `data/mock/expected_classifications.csv` — ground truth mapped to above

### Phase 4 — Observability
11. `src/observability/tracing.py` — Langfuse singleton, create_trace, create_langfuse_handler
12. `src/observability/metrics.py` — ProcessingMetrics, latency tracking, performance summary

### Phase 5 — MCP Server
13. `src/mcp_server/server.py` — FastMCP with `create_ticket`, `update_ticket`, `get_tickets` tools

### Phase 6 — Agents
14. `src/utils/csv_parser.py` — CSV parsing utilities
15. `src/agents/csv_agent.py`
16. `src/agents/classifier.py`
17. `src/agents/bug_analyzer.py`
18. `src/agents/feature_extractor.py`
19. `src/agents/ticket_creator.py` (MCP client wrapper)
20. `src/agents/quality_critic.py`

### Phase 7 — Graph Orchestration
21. `src/graph/workflow.py` — StateGraph, conditional edges, compile

### Phase 8 — Streamlit UI
22. `streamlit_app/app.py`
23. `streamlit_app/pages/1_Upload_and_Process.py`
24. `streamlit_app/pages/2_Dashboard.py`
25. `streamlit_app/pages/3_Analytics.py`
26. `streamlit_app/pages/4_Configuration.py`

### Phase 9 — Tests & Documentation
27. All test files
28. `README.md`

---

## Database Schema (SQLite — `data/db/feedback.db`)

### Table: `raw_feedback`
```sql
CREATE TABLE IF NOT EXISTS raw_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL,
    source_type     TEXT NOT NULL,        -- 'app_store_review' | 'support_email' | 'manual_input'
    source_file     TEXT,
    content_text    TEXT NOT NULL,
    subject         TEXT,
    sender          TEXT,
    rating          INTEGER,
    platform        TEXT,
    priority_hint   TEXT,
    original_date   TEXT,
    app_version     TEXT,
    raw_json        TEXT,                 -- full original row as JSON
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, source_type)
);
```

### Table: `tickets`
```sql
CREATE TABLE IF NOT EXISTS tickets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id           TEXT NOT NULL UNIQUE,    -- 'TKT-YYYYMMDD-NNN'
    feedback_id         INTEGER NOT NULL,
    category            TEXT NOT NULL,
    confidence          REAL NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    priority            TEXT NOT NULL,
    severity            TEXT,
    technical_details   TEXT,                    -- JSON
    feature_details     TEXT,                    -- JSON
    suggested_actions   TEXT,                    -- JSON array
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
```

### Table: `processing_log`
```sql
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
```

---

## LangGraph Pipeline Design

### PipelineState (TypedDict in `src/models/state.py`)

```python
class PipelineState(TypedDict):
    batch_id: str
    trace_id: str
    feedback_items: list[dict]           # all items to process
    current_index: int
    total_items: int
    current_item: Optional[dict]
    classification: Optional[dict]       # category, confidence, reasoning
    analysis: Optional[dict]             # technical_details or feature_details
    ticket: Optional[dict]               # created ticket data
    quality_review: Optional[dict]       # score, approved, notes
    current_agent: str                   # for real-time UI status
    status: str                          # pipeline status
    error_message: Optional[str]
    revision_count: int
    completed_tickets: Annotated[list[str], operator.add]
```

### Graph Flow (Conditional Branching)

```
ingest → classify ─┬─ Bug ──────────→ bug_analyze ──→ create_ticket → quality_review ─┬─ approved → finalize → next_item ─┬─ more → ingest
                    ├─ Feature Req ──→ feature_extract ─┘                               │                                    └─ done → END
                    └─ Other ────────────────────────────┘                               └─ rejected (< 2 revisions) → create_ticket
```

Key routing functions:
- `_route_after_classification(state)` → returns `"bug_analyze"` | `"feature_extract"` | `"create_ticket"`
- `_route_after_review(state)` → returns `"finalize"` (approved OR max revisions) | `"create_ticket"` (rejected)
- `_route_next_or_end(state)` → returns `"ingest"` (more items) | END

---

## Agent Designs

### 1. CSV Agent (`csv_agent.py`) — Deterministic, no LLM
- Parses CSV files using `csv.DictReader`
- Normalizes columns across different CSV formats (reviews vs emails)
- Stores each row in `raw_feedback` table
- Returns list of `FeedbackItemState` dicts

### 2. Feedback Classifier (`classifier.py`) — LLM-based
- **System prompt**: Expert feedback classifier for productivity app
- **Input**: feedback text + rating + platform context
- **Output JSON**: `{category, confidence, reasoning}`
- Categories: Bug, Feature Request, Praise, Complaint, Spam
- Uses configurable confidence threshold (default 0.7)

### 3. Bug Analyzer (`bug_analyzer.py`) — LLM-based, only for Bugs
- **System prompt**: Senior QA engineer analyzing bug reports
- **Output JSON**: `{severity, affected_component, platform_details, steps_to_reproduce, expected_behavior, actual_behavior, suggested_title, suggested_priority, suggested_actions}`

### 4. Feature Extractor (`feature_extractor.py`) — LLM-based, only for Feature Requests
- **System prompt**: Product manager analyzing feature requests
- **Output JSON**: `{feature_name, description, user_impact, demand_signal, existing_alternatives, suggested_title, suggested_priority, suggested_actions}`

### 5. Ticket Creator (`ticket_creator.py`) — LLM + MCP Client
- LLM generates ticket title/description from classification + analysis
- MCP client calls `create_ticket` tool on the FastMCP server via stdio transport
- Generates ticket IDs in format `TKT-YYYYMMDD-NNN`

### 6. Quality Critic (`quality_critic.py`) — LLM-based
- **System prompt**: Senior engineering manager reviewing tickets
- Scores on 5 criteria (title clarity, description completeness, priority accuracy, technical accuracy, actionability) — total 0-10
- Score >= 7: approved. Score < 7 and revisions < 2: send back to Ticket Creator
- **Output JSON**: `{score, breakdown, approved, notes, revision_suggestions}`

---

## MCP Server Design (`src/mcp_server/server.py`)

Built with FastMCP, runs via stdio transport, connects to `data/db/feedback.db`:

| Tool | Purpose |
|---|---|
| `create_ticket(feedback_id, category, confidence, title, description, priority, ...)` | Insert new ticket into `tickets` table |
| `update_ticket(ticket_id, title?, description?, priority?, quality_score?, ...)` | Update existing ticket fields |
| `get_tickets(category?, priority?, quality_status?, limit?)` | Query tickets with filters |

The Ticket Creator agent launches this server as a subprocess and communicates via MCP stdio protocol.

---

## Streamlit UI Design

### Page 1: Upload & Process
- `st.file_uploader()` for CSV files + radio for source type
- `st.text_area()` for manual review/feedback input
- "Process" button triggers LangGraph pipeline
- **Real-time status**: `st.status()` + `st.empty()` containers updated per-agent via `st.session_state`, showing current agent name, progress bar, and intermediate results

### Page 2: Dashboard
- Tabbed view: All Tickets | Bugs | Feature Requests | Other | Needs Review
- `st.dataframe()` with ticket list (ID, Title, Category, Priority, Quality Score)
- Expandable detail view per ticket
- Manual override: edit title/priority/category + Save/Approve/Reject buttons

### Page 3: Analytics
- `st.metric()` cards: Total Processed, Tickets Created, Avg Quality Score, Error Rate
- Classification distribution bar chart
- Priority distribution pie chart
- Quality score histogram
- Classification accuracy vs `expected_classifications.csv` (confusion matrix)

### Page 4: Configuration
- API key status (masked) + connection test buttons
- Sliders: confidence threshold (0.5-1.0), quality auto-approve threshold (5-10), max revisions (1-5)
- Model display (gpt-5.4), temperature slider

---

## Langfuse Integration

### Setup (`src/observability/tracing.py`)
- Singleton `Langfuse` client initialized from config
- `create_trace(name, session_id)` → root trace per batch
- `create_langfuse_handler(trace_id)` → LangChain `CallbackHandler` for LLM calls
- `traced_span(trace, name)` → context manager for timing agent nodes

### Where tracing is added
1. **Batch start**: create root trace
2. **Each agent node**: wrapped in `traced_span` for latency tracking
3. **Each LLM call**: `LangfuseCallbackHandler` passed as callback to `ChatOpenAI.ainvoke()`
4. **Scores**: classification confidence, quality score, error flags
5. **Batch end**: update trace with summary output

---

## Dependencies (`requirements.txt`)

```
langgraph>=1.0.0
langchain>=0.3.0
langchain-core>=0.3.0
langchain-openai>=0.3.0
langfuse>=3.14.0
fastmcp>=0.1.0
mcp>=1.0.0
streamlit>=1.38.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
plotly>=5.0.0
```

---

## Verification Plan

1. **Unit tests**: Each agent tested individually with mocked LLM responses
2. **Integration test**: Full pipeline with mocked LLM, verify Bug/Feature/Other paths
3. **MCP server test**: Direct function calls to verify SQLite CRUD
4. **Database test**: init_db() creates tables, insert/query helpers work
5. **End-to-end manual test**:
   - Upload `app_store_reviews.csv` → verify all rows parsed and stored
   - Verify classification matches expected for ≥80% of items
   - Verify bug tickets have `technical_details`, feature tickets have `feature_details`
   - Verify quality critic approves good tickets, rejects poor ones
   - Verify revision loop works (ticket improved on second pass)
   - Edit a ticket manually → verify changes persist
   - Check Langfuse dashboard for traces with correct spans and scores
   - Upload malformed CSV → verify graceful error handling
6. **Run Streamlit**: `streamlit run streamlit_app/app.py` and walk through all 4 pages
