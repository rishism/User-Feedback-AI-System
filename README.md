# Intelligent User Feedback Analysis and Action System

A multi-agent AI system that automates the processing of user feedback from app store reviews and support emails. Built with **LangChain + LangGraph** for agent orchestration, **FastMCP** for ticket management via MCP (SSE transport), **Streamlit** for the UI, and **Langfuse** for observability.

## Architecture

### Hybrid Supervisor Pipeline (LangGraph)

The pipeline uses a **hybrid supervisor** pattern — most transitions are deterministic graph edges, but an LLM-powered supervisor makes routing decisions at two branching points:

1. **Post-classification**: Which specialist agent should analyze this feedback? (bug_analyzer, feature_extractor, or skip to ticketing)
2. **Post-quality-review**: Is the ticket good enough to finalize, or should it be sent back for revision?

```
CSV Upload / Manual Input (Streamlit)
  → Ingest (CSV Agent: parse & store in SQLite)
    → Classifier (LLM: Bug / Feature / Praise / Complaint / Spam)
      → Supervisor (LLM routing decision)
        → Bug Analyzer (ReAct agent)  ───────┐
        → Feature Extractor (ReAct agent) ───┤
        → Direct to ticketing ───────────────┘
          → Ticket Creator (ReAct agent + MCP tool-calling)
            → Quality Critic (ReAct agent + MCP tool-calling)
              → Supervisor (LLM routing decision)
                → Approved? → Finalize → Next item (or END)
                → Rejected? → Back to Ticket Creator (max 2 revisions)
```

Agents communicate with the ticket database through an **MCP server** running on SSE transport (`localhost:8765`). The ticket creator and quality critic use ReAct-style tool-calling to create, update, and query tickets autonomously.

### Why Hybrid Supervisor?

LangGraph supports a spectrum of multi-agent routing patterns, each with different tradeoffs:

| Pattern | How it works | Tradeoff |
|---|---|---|
| **Sequential** | `A → B → C → D` — all edges hardcoded | Simple but inflexible; can't skip steps or reroute based on content |
| **Full Supervisor** | Every node returns to a central supervisor LLM, which picks the next step | Maximum flexibility but expensive — requires an LLM call at every transition (6-8x per item) |
| **Hybrid Supervisor** | Deterministic edges where the flow is obvious, LLM routing only at genuine decision points | Best balance of flexibility and cost — supervisor is called only 2x per item |

This project uses the **hybrid** approach. Transitions like `classify → supervisor` or `bug_analyzer → ticket_creator` are always the same, so they're hardcoded edges — no point paying for an LLM call to decide something predetermined. The supervisor only activates at the two points where the decision genuinely depends on content: routing to the right analyzer after classification, and deciding whether a ticket passes quality review.

### Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Agent Framework | LangChain + LangGraph |
| LLM | OpenAI GPT (gpt-5.4) |
| Ticket System | FastMCP (SSE transport) + SQLite |
| Database | SQLite |
| Visualization | Plotly |
| UI | Streamlit |
| Observability | Langfuse |

## Setup

### 1. Prerequisites

- Python 3.12+
- An OpenAI API key

### 2. Install Dependencies

```bash
cd User-Feedback-AI-System
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install plotly
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your API keys:
# - OPENAI_API_KEY (required)
# - LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY (optional, for tracing)
```

### 4. Initialize Database

The database is auto-initialized on first run, but you can also initialize it manually:

```bash
python -c "from src.db.database import init_db; init_db()"
```

## Running the Application

### Streamlit UI

```bash
streamlit run streamlit_app/app.py
```

This opens the web interface with 4 pages:

1. **Upload & Process** - Upload CSV files or submit manual feedback
2. **Dashboard** - View, search, and edit generated tickets
3. **Analytics** - Charts, metrics, and classification accuracy
4. **Configuration** - Adjust thresholds, agent iterations, and test API connections

The MCP server is auto-started on the first pipeline run (no manual setup needed).

### Processing Mock Data

The `data/mock/` directory contains sample datasets:

- `app_store_reviews.csv` - 25 app store reviews
- `support_emails.csv` - 15 support emails
- `expected_classifications.csv` - Ground truth for accuracy testing

Upload these via the Streamlit UI to see the system in action.

### Output CSV Files

After processing feedback, the system auto-generates three output CSV files in `data/output/`:

| File | Path | Description |
|---|---|---|
| **generated_tickets.csv** | `data/output/generated_tickets.csv` | All generated tickets with category, priority, quality score, and details |
| **processing_log.csv** | `data/output/processing_log.csv` | Agent processing history with latency, status, and trace IDs |
| **metrics.csv** | `data/output/metrics.csv` | Aggregated metrics: totals, accuracy, per-category counts, per-agent latency |

These files are regenerated each time feedback is processed via the Upload & Process page.

## Project Structure

```
User_Feedback_AI_system/
├── data/mock/                  # Mock CSV datasets
├── data/output/                # Auto-generated output CSV files
├── src/
│   ├── config.py               # pydantic-settings configuration
│   ├── models/
│   │   ├── schemas.py          # Pydantic data models
│   │   └── state.py            # LangGraph PipelineState
│   ├── db/
│   │   ├── database.py         # SQLite init and connection
│   │   └── queries.py          # SQL helper functions
│   ├── agents/
│   │   ├── csv_agent.py        # CSV parsing and ingestion
│   │   ├── classifier.py       # LLM-based 5-category classifier
│   │   ├── bug_analyzer.py     # Bug technical detail extraction (ReAct)
│   │   ├── feature_extractor.py # Feature request analysis (ReAct)
│   │   ├── ticket_creator.py   # Ticket generation via MCP tools (ReAct)
│   │   ├── quality_critic.py   # Ticket quality review via MCP tools (ReAct)
│   │   └── supervisor.py       # LLM-driven routing supervisor
│   ├── tools/
│   │   ├── mcp_tools.py        # MCP SSE client + server auto-start
│   │   └── db_tools.py         # LangChain @tool wrappers for DB queries
│   ├── graph/
│   │   └── workflow.py         # LangGraph StateGraph definition
│   ├── mcp_server/
│   │   └── server.py           # FastMCP ticket management server (SSE)
│   ├── observability/
│   │   ├── tracing.py          # Langfuse integration
│   │   └── metrics.py          # Processing metrics
│   └── utils/
│       ├── csv_parser.py       # CSV parsing utilities
│       └── csv_exporter.py     # CSV export utilities
├── streamlit_app/
│   ├── app.py                  # Main entry point
│   └── pages/                  # Streamlit multi-page app
├── tests/                      # Test suite (43 tests)
├── .env.example                # Environment template
├── pyproject.toml              # Project metadata
└── requirements.txt            # Dependencies
```

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Configuration

All settings can be configured via the `.env` file or the Streamlit Configuration page:

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | - | OpenAI API key (required) |
| `OPENAI_MODEL` | `gpt-5.4` | OpenAI model ID |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.7` | Min confidence for classification |
| `QUALITY_AUTO_APPROVE_THRESHOLD` | `7.0` | Min quality score for auto-approval |
| `MAX_REVISION_COUNT` | `2` | Max ticket revision attempts |
| `MAX_AGENT_ITERATIONS` | `5` | Max ReAct agent tool-calling iterations |
| `LANGFUSE_PUBLIC_KEY` | - | Langfuse public key (optional) |
| `LANGFUSE_SECRET_KEY` | - | Langfuse secret key (optional) |

## Langfuse Setup (Optional)

1. Create an account at [cloud.langfuse.com](https://cloud.langfuse.com)
2. Create a new project
3. Copy your public and secret keys to `.env`
4. All LLM calls and agent traces will appear in your Langfuse dashboard

## MCP Server

The ticket management MCP server runs on **SSE transport** at `http://127.0.0.1:8765/sse`. It is auto-started by the pipeline on first use — no manual setup needed.

To run it standalone:

```bash
python src/mcp_server/server.py
```

It provides three tools:
- `create_ticket` - Create a new ticket in SQLite
- `update_ticket` - Update ticket fields (content, quality review)
- `get_tickets` - Query tickets with filters
