# Setup and Usage

## Prerequisites

- **Python 3.12+** (required — see `pyproject.toml:9`)
- **OpenAI API key** (required — GPT-5.4 powers all LLM agents)
- **Langfuse account** (optional — for LLM tracing and observability)

---

## Installation

### Clone Repository

```bash
git clone <repository-url>
cd User_Feedback_AI_system
```

### Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### Install Dependencies

**Option 1: pip with requirements.txt**

```bash
pip install -r requirements.txt
```

**Option 2: pip with pyproject.toml (includes dev dependencies)**

```bash
pip install -e ".[dev]"
```

This installs all runtime dependencies plus `pytest>=8.0.0` and `pytest-asyncio>=0.24.0` for testing.

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `langgraph` | >= 1.0.0 | StateGraph pipeline orchestration |
| `langchain` | >= 0.3.0 | LLM framework core |
| `langchain-core` | >= 0.3.0 | Message types, callback system |
| `langchain-openai` | >= 0.3.0 | ChatOpenAI wrapper |
| `langfuse` | >= 3.14.0 | LLM tracing and observability |
| `fastmcp` | >= 2.0.0 | MCP server and client |
| `streamlit` | >= 1.38.0 | Web UI framework |
| `pydantic` | >= 2.0.0 | Data validation models |
| `pydantic-settings` | >= 2.0.0 | Environment-based configuration |
| `python-dotenv` | >= 1.0.0 | `.env` file loading |
| `plotly` | >= 5.0.0 | Interactive charts |

---

## Configuration

### Environment File

Copy the example and fill in your keys:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key (e.g., `sk-...`) |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-5.4` | OpenAI model name |
| `OPENAI_TEMPERATURE` | `0.1` | LLM temperature (lower = more deterministic) |
| `LANGFUSE_PUBLIC_KEY` | `""` | Langfuse public key for tracing |
| `LANGFUSE_SECRET_KEY` | `""` | Langfuse secret key for tracing |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse instance URL |
| `DB_PATH` | `data/db/feedback.db` | SQLite database file path |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.7` | Minimum confidence for classification |
| `QUALITY_AUTO_APPROVE_THRESHOLD` | `7.0` | Minimum quality score for auto-approval |
| `MAX_REVISION_COUNT` | `2` | Maximum ticket revision attempts |
| `LOG_LEVEL` | `INFO` | Python logging level |

Configuration is managed by Pydantic Settings (`src/config.py:6-37`) which reads from `.env` automatically.

---

## Initialize Database

The database is **auto-initialized** on Streamlit startup (`streamlit_app/app.py:24-27`). To initialize manually:

```bash
python -c "from src.db.database import init_db; init_db()"
```

This creates `data/db/feedback.db` with 3 tables: `raw_feedback`, `tickets`, `processing_log`. The operation is idempotent (safe to run multiple times).

---

## Running the Application

### Start Streamlit

```bash
streamlit run streamlit_app/app.py
```

The app opens at `http://localhost:8501` with 4 pages:
1. **Upload & Process** — Upload CSVs or submit manual feedback
2. **Dashboard** — View and manage tickets
3. **Analytics** — Charts and classification accuracy
4. **Configuration** — API keys, thresholds, connection tests

### Processing Mock Data

The project includes sample data in `data/mock/`:

| File | Description |
|------|-------------|
| `app_store_reviews.csv` | Sample app store reviews with review_id, review_text, user_name, rating, platform, date, app_version |
| `support_emails.csv` | Sample support emails with email_id, body, subject, sender_email, priority, timestamp |
| `expected_classifications.csv` | Ground truth classifications for accuracy analysis |

To process mock data:
1. Start the Streamlit app
2. Navigate to **Upload & Process**
3. Upload `data/mock/app_store_reviews.csv` or `data/mock/support_emails.csv`
4. Select source type (or use Auto-detect)
5. Click **Process CSV**

The pipeline processes each item through all agents with real-time status updates.

---

## Running Tests

```bash
pytest tests/ -v
```

### Test Configuration

From `pyproject.toml:33-35`:
- `testpaths = ["tests"]`
- `asyncio_mode = "auto"`

### Test Files

| Test File | Tests |
|-----------|-------|
| `test_database.py` | Table creation, feedback CRUD, ticket queries, processing log |
| `test_mcp_server.py` | MCP tool execution (create, update, get tickets) |
| `test_classifier.py` | Classification logic, fallback behavior on invalid JSON |
| `test_bug_analyzer.py` | Bug analysis extraction, fallback defaults |
| `test_feature_extractor.py` | Feature extraction, fallback defaults |
| `test_ticket_creator.py` | Ticket generation and storage |
| `test_quality_critic.py` | Quality scoring, auto-approve, rejection, fallback |
| `test_csv_agent.py` | CSV type detection, parsing, content extraction |
| `test_graph_workflow.py` | Routing functions, conditional edges, batch loop |

### Test Approach

- **Agent tests** mock `update_feedback_status` and `log_processing` to avoid DB dependencies, and mock the LLM response
- **Database tests** use `tempfile.mkstemp` for isolated SQLite instances
- **MCP tests** patch `DB_PATH` with a temporary database
- **Workflow tests** test routing functions directly with mock state dicts

---

## Running MCP Server Standalone

```bash
python -m src.mcp_server.server
```

This starts the FastMCP server on stdio transport. Connect with any MCP-compatible client to use the `create_ticket`, `update_ticket`, and `get_tickets` tools.

---

## Troubleshooting

### OpenAI API Key Issues

**Symptom:** `st.error("OpenAI API Key: Not set")` on Configuration page

**Fix:** Ensure `OPENAI_API_KEY` is set in your `.env` file. Test the connection using the **Test OpenAI Connection** button on the Configuration page.

### Database Issues

**Symptom:** `sqlite3.OperationalError: unable to open database file`

**Fix:**
- Ensure the `data/db/` directory exists and is writable
- Check that `DB_PATH` in `.env` is a valid relative or absolute path
- WAL mode requires the filesystem to support it (most do)

**Symptom:** Stale data or missing tables

**Fix:** Run `python -c "from src.db.database import init_db; init_db()"` to recreate tables.

### Langfuse Connection

**Symptom:** `"Langfuse Key: Not set. Tracing disabled."` warning

**This is expected if you haven't configured Langfuse.** The system runs normally without tracing — all `tracing.py` functions return `None` gracefully.

**Fix (if tracing desired):** Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_HOST` in `.env`.

### Import Errors

**Symptom:** `ModuleNotFoundError: No module named 'src'`

**Fix:** Run the Streamlit app from the project root directory. The app adds the project root to `sys.path` (`app.py:7`), but this requires the working directory to be correct.

### CSV Parsing Errors

**Symptom:** `ValueError: Cannot detect CSV type from headers`

**Fix:** Ensure your CSV has the expected headers:
- App store reviews: must contain `review_id` or `review_text`
- Support emails: must contain `email_id` or `body`

Alternatively, select the source type manually instead of Auto-detect.

### Pipeline Processing Errors

**Symptom:** `Pipeline error: ...` displayed after clicking Process CSV

**Common causes:**
- Invalid or expired OpenAI API key
- Network connectivity issues
- Rate limiting from the OpenAI API

Check the full traceback displayed in the error section for details.

---

## Related Documentation

- [Project Overview](project_overview.md) — Architecture and design decisions
- [Configuration](streamlit_ui.md#page-4-configuration) — Runtime settings via the UI
- [Database Schema](database_schema.md) — Table structure and queries
