# Intelligent User Feedback Analysis and Action System

A multi-agent AI system that automates the processing of user feedback from app store reviews and support emails. Built with **LangChain + LangGraph** for agent orchestration, **FastMCP** for ticket management, **Streamlit** for the UI, and **Langfuse** for observability.

## Architecture

### 6-Agent Pipeline (LangGraph)

```
CSV Upload / Manual Input (Streamlit)
  -> CSV Agent (parse & store in SQLite)
    -> Feedback Classifier (LLM: Bug/Feature/Praise/Complaint/Spam)
      -> Bug Analyzer (if Bug) --------+
      -> Feature Extractor (if Feature)-+-> Ticket Creator (MCP -> SQLite)
      -> Direct (if other) ------------+      -> Quality Critic
                                                  -> Approved? -> Done
                                                  -> Rejected? -> Revise (max 2x)
```

### Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12 |
| Agent Framework | LangChain + LangGraph |
| LLM | OpenAI GPT (gpt-5.4) |
| Ticket System | FastMCP + SQLite |
| Database | SQLite |
| UI | Streamlit |
| Observability | Langfuse |

## Setup

### 1. Prerequisites

- Python 3.12+
- An OpenAI API key

### 2. Install Dependencies

```bash
cd User_Feedback_AI_system
pip install -r requirements.txt
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
4. **Configuration** - Adjust thresholds and test API connections

### Processing Mock Data

The `data/mock/` directory contains sample datasets:

- `app_store_reviews.csv` - 25 app store reviews
- `support_emails.csv` - 15 support emails
- `expected_classifications.csv` - Ground truth for accuracy testing

Upload these via the Streamlit UI to see the system in action.

## Project Structure

```
User_Feedback_AI_system/
├── data/mock/                  # Mock CSV datasets
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
│   │   ├── bug_analyzer.py     # Bug technical detail extraction
│   │   ├── feature_extractor.py # Feature request analysis
│   │   ├── ticket_creator.py   # Ticket generation + MCP client
│   │   └── quality_critic.py   # Ticket quality review
│   ├── graph/
│   │   └── workflow.py         # LangGraph StateGraph definition
│   ├── mcp_server/
│   │   └── server.py           # FastMCP ticket management server
│   ├── observability/
│   │   ├── tracing.py          # Langfuse integration
│   │   └── metrics.py          # Processing metrics
│   └── utils/
│       └── csv_parser.py       # CSV parsing utilities
├── streamlit_app/
│   ├── app.py                  # Main entry point
│   └── pages/                  # Streamlit multi-page app
├── tests/                      # Test suite
├── .env.example                # Environment template
├── pyproject.toml              # Project metadata
└── requirements.txt            # Dependencies
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Configuration

All settings can be configured via the `.env` file:

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | - | OpenAI API key (required) |
| `OPENAI_MODEL` | `gpt-5.4` | OpenAI model ID |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.7` | Min confidence for classification |
| `QUALITY_AUTO_APPROVE_THRESHOLD` | `7.0` | Min quality score for auto-approval |
| `MAX_REVISION_COUNT` | `2` | Max ticket revision attempts |
| `LANGFUSE_PUBLIC_KEY` | - | Langfuse public key (optional) |
| `LANGFUSE_SECRET_KEY` | - | Langfuse secret key (optional) |

## Langfuse Setup (Optional)

1. Create an account at [cloud.langfuse.com](https://cloud.langfuse.com)
2. Create a new project
3. Copy your public and secret keys to `.env`
4. All LLM calls and agent traces will appear in your Langfuse dashboard

## MCP Server

The ticket management MCP server can be run standalone:

```bash
python -m src.mcp_server.server
```

It provides three tools:
- `create_ticket` - Create a new ticket in SQLite
- `update_ticket` - Update ticket fields
- `get_tickets` - Query tickets with filters
