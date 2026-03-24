# Streamlit UI

## Overview

The Streamlit application provides a 4-page web interface for uploading feedback, monitoring processing, managing tickets, viewing analytics, and configuring the system. The app runs on `localhost:8501` by default.

All UI code is in `streamlit_app/`.

## App Entry Point (`streamlit_app/app.py`)

### Page Configuration (`app.py:11-16`)

```python
st.set_page_config(
    page_title="Feedback Analysis System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
```

### Database Initialization (`app.py:23-27`)

On first load, the app initializes the SQLite database:

```python
if "db_initialized" not in st.session_state:
    from src.db.database import init_db
    init_db()
    st.session_state.db_initialized = True
```

### Sidebar (`app.py:30-36`)

Displays system configuration:
- Model name (e.g., `gpt-5.4`)
- Confidence threshold (e.g., `0.7`)
- Quality threshold (e.g., `7.0`)

### Summary Metrics (`app.py:41-58`)

The home page shows 4 metric cards queried directly from SQLite:

| Metric | Query |
|--------|-------|
| Total Feedback | `SELECT COUNT(*) FROM raw_feedback` |
| Tickets Created | `SELECT COUNT(*) FROM tickets` |
| Tickets Approved | `SELECT COUNT(*) FROM tickets WHERE quality_status = 'approved'` |
| Avg Quality Score | `SELECT AVG(quality_score) FROM tickets WHERE quality_score IS NOT NULL` |

### Path Setup (`app.py:6-7`)

Adds the project root to `sys.path` so `src` imports work:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

All page files repeat this pattern (`pages/*.py:5-6`).

---

## Page 1: Upload & Process

**File:** `streamlit_app/pages/1_Upload_and_Process.py`

### CSV Upload (`1_Upload_and_Process.py:24-38`)

- **File uploader:** `st.file_uploader("Choose a CSV file", type=["csv"])` (`line 28`)
- **Source type selector:** Radio buttons with options: `Auto-detect`, `App Store Reviews`, `Support Emails` (`lines 34-38`)
- Auto-detection uses `detect_csv_type()` from `src/utils/csv_parser.py` which examines CSV headers:
  - `review_id` or `review_text` → app store reviews
  - `email_id` or `body` → support emails
- CSV is parsed via `parse_csv_file()` which dispatches to the appropriate parser (`line 181-183`)

### Manual Input (`1_Upload_and_Process.py:41-58`)

An expandable form for submitting single feedback items:

| Widget | Type | Description |
|--------|------|-------------|
| Feedback text | `st.text_area` | The feedback content (required) |
| Platform | `st.selectbox` | Google Play, App Store, Email, Other |
| Rating | `st.slider` | 0-5 (0 = no rating) |
| Subject | `st.text_input` | Optional subject line |

Manual items are created as `FeedbackItem` with `source_type="manual_input"` and `source_id="MANUAL-{uuid_hex[:8]}"` (`lines 191-198`).

### Real-Time Processing (`1_Upload_and_Process.py:70-153`)

The `process_feedback()` function orchestrates pipeline execution:

1. **Ingest:** Calls `ingest_feedback_items(items)` to store in DB and get state dicts (`line 76`)
2. **Status container:** Creates `st.container()` and `st.progress(0)` for real-time updates (`lines 84-85`)
3. **Build pipeline:** Calls `build_pipeline(status_callback=status_callback)` (`lines 120-122`)
4. **Create state:** Calls `create_initial_state(state_items)` (`line 124`)
5. **Execute:** Calls `pipeline.invoke(initial_state)` inside `st.status()` widget (`lines 127-128`)
6. **Display results:** Shows all collected status messages and completed ticket IDs (`lines 130-146`)

### Status Callback (`1_Upload_and_Process.py:89-116`)

Called by each graph node via the `_with_callback()` wrapper. Displays:

- Agent name and status for every node
- Classification category and confidence (for classifier)
- Ticket ID (for ticket creator)
- Quality score and approval status (for quality critic)
- Progress bar updates: `(current_index + 1) / total_items` (`lines 114-116`)

### Error Handling (`1_Upload_and_Process.py:148-153`)

Pipeline errors are caught and displayed with `st.error()` and a full traceback in `st.code()`.

<!-- ![Upload & Process Page](../test_screenshots/upload_and_process.png) -->

---

## Page 2: Dashboard

**File:** `streamlit_app/pages/2_Dashboard.py`

### Tab Navigation (`2_Dashboard.py:19-21`)

Five tabs for filtering tickets:

| Tab | Filter |
|-----|--------|
| All Tickets | No filter — `get_tickets(limit=100)` |
| Bugs | `get_tickets(category="Bug")` |
| Feature Requests | `get_tickets(category="Feature Request")` |
| Other | SQL: `category NOT IN ('Bug', 'Feature Request')` |
| Needs Review | `quality_status="revision_needed"` + `quality_status="pending"` |

### Ticket Table (`2_Dashboard.py:24-41`)

Displays a `pandas.DataFrame` with columns:
- `ticket_id`, `title`, `category`, `priority`, `quality_score`, `quality_status`

Uses `st.dataframe()` with `use_container_width=True` and `hide_index=True`.

### Expandable Detail View (`2_Dashboard.py:44-72`)

Each ticket has an expandable section showing:

1. **Header:** Category, Priority, Quality Score/Status (3 columns)
2. **Description:** Full ticket description via `st.text()`
3. **Technical Details:** Rendered as JSON (`st.json()`) if present
4. **Feature Details:** Rendered as JSON (`st.json()`) if present
5. **Quality Notes:** Critic's review notes
6. **Original Feedback:** Fetched via `get_feedback_by_id(ticket["feedback_id"])` — provides full traceability from ticket back to source feedback (`lines 69-72`)

### Manual Override (`2_Dashboard.py:74-122`)

Three actions per ticket:

| Button | Action | Updates |
|--------|--------|---------|
| **Save** | Edit title and priority | `title`, `priority`, `manually_edited=1`, `edited_by="streamlit_user"` |
| **Approve** | Manually approve | `quality_status="approved"`, `manually_edited=1`, `edited_by="streamlit_user"` |
| **Reject** | Send for revision | `quality_status="revision_needed"`, `manually_edited=1`, `edited_by="streamlit_user"` |

All actions call `update_ticket()` and trigger `st.rerun()` to refresh the page.

<!-- ![Dashboard Page](../test_screenshots/dashboard.png) -->

---

## Page 3: Analytics

**File:** `streamlit_app/pages/3_Analytics.py`

### Summary Metrics (`3_Analytics.py:22-39`)

Four metric cards:
- **Total Processed:** `COUNT(*) FROM raw_feedback`
- **Tickets Created:** `COUNT(*) FROM tickets`
- **Avg Quality Score:** `AVG(quality_score) FROM tickets`
- **Errors:** `COUNT(*) FROM processing_log WHERE status = 'error'`

### Classification Distribution (`3_Analytics.py:44-66`)

Two side-by-side charts using Plotly:
- **Bar chart:** Tickets by category (color-coded by category)
- **Pie chart:** Category distribution as percentages

Data source: `SELECT category, COUNT(*) as count FROM tickets GROUP BY category`

### Priority Distribution (`3_Analytics.py:69-87`)

Bar chart with semantic color mapping:

| Priority | Color |
|----------|-------|
| Critical | Red (`#dc3545`) |
| High | Orange (`#fd7e14`) |
| Medium | Yellow (`#ffc107`) |
| Low | Green (`#28a745`) |

### Quality Score Distribution (`3_Analytics.py:90-105`)

Histogram of quality scores with:
- 10 bins spanning the score range
- A **dashed green vertical line** at `7.0` marking the approval threshold (`line 103-104`)

### Agent Processing Latency (`3_Analytics.py:108-122`)

Bar chart showing average latency (ms) per agent:
- Data source: `SELECT agent_name, AVG(latency_ms) FROM processing_log GROUP BY agent_name`
- Helps identify bottleneck agents

### Classification Accuracy (`3_Analytics.py:124-182`)

Compares pipeline predictions against ground truth from `data/mock/expected_classifications.csv`:

1. **Joins** actual tickets with expected classifications on `source_id` + `source_type` (`lines 144-150`)
2. **Accuracy metric:** Percentage of matching category predictions (`lines 154-157`)
3. **Confusion matrix:** Uses `sklearn.metrics.confusion_matrix` if available (`lines 160-168`). Falls back to a simple comparison table if sklearn is not installed (`lines 170-173`).

The `expected_classifications.csv` must contain `source_id`, `source_type`, and `category` columns.

<!-- ![Analytics Page](../test_screenshots/analytics.png) -->

---

## Page 4: Configuration

**File:** `streamlit_app/pages/4_Configuration.py`

### API Key Status (`4_Configuration.py:14-31`)

Displays masked API keys:
- **OpenAI:** Shows first 8 + `...` + last 4 characters, or error if not set
- **Langfuse:** Shows masked key, or warning that tracing is disabled

### Connection Tests (`4_Configuration.py:34-59`)

Two test buttons:

| Button | Test | Method |
|--------|------|--------|
| Test OpenAI Connection | Sends `"Say 'OK' in one word."` to the LLM | `ChatOpenAI.invoke()` |
| Test Langfuse Connection | Initializes Langfuse client | `get_langfuse()` |

Success/failure is displayed inline with `st.success()` or `st.error()`.

### Threshold Sliders (`4_Configuration.py:63-97`)

| Setting | Widget | Range | Default | Description |
|---------|--------|-------|---------|-------------|
| Confidence Threshold | `st.slider` | 0.5-1.0 | 0.7 | Minimum classification confidence |
| Auto-Approve Threshold | `st.slider` | 5.0-10.0 | 7.0 | Minimum quality score for auto-approval |
| Maximum Revisions | `st.number_input` | 1-5 | 2 | Max revision attempts before force-approve |
| Temperature | `st.slider` | 0.0-1.0 | 0.1 | LLM temperature |

### Model Display (`4_Configuration.py:104`)

The model name is shown as a **read-only** text input (`disabled=True`).

### Session-Based Settings (`4_Configuration.py:117-134`)

Clicking "Apply Settings" stores overrides in `st.session_state["config_overrides"]`:

```python
st.session_state["config_overrides"] = {
    "confidence_threshold": confidence_threshold,
    "quality_threshold": quality_threshold,
    "max_revisions": max_revisions,
    "temperature": temperature,
}
```

These settings apply only to the current browser session. For persistent changes, users must update the `.env` file.

<!-- ![Configuration Page](../test_screenshots/configuration.png) -->

---

## Related Documentation

- [LangGraph Pipeline](langgraph_pipeline.md) — Pipeline invoked from Upload & Process page
- [Database Schema](database_schema.md) — Data displayed in Dashboard and Analytics
- [Setup and Usage](setup_and_usage.md) — How to run the Streamlit app
- [Observability](observability.md) — Metrics displayed in Analytics
