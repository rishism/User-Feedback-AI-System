test the Streamlit app using Playwright MCP in Chrome, and I'll:
  - Navigate to http://localhost:8501
  - Take snapshots of each page
  - Upload the mock CSV and trigger processing
  - Verify tickets appear on the Dashboard
  - Check the Analytics page

---------------------

  Read and understand the entire codebase in this project directory. Then create the following markdown documentation files in the documentation/ folder:

  1. **documentation/project_overview.md** — High-level summary of the project: what it does, the business problem it solves, the 6-agent architecture,
  tech stack (LangChain + LangGraph, OpenAI GPT-5.4, FastMCP, SQLite, Streamlit, Langfuse), and a system architecture diagram in ASCII/mermaid showing the
  data flow from CSV upload through all agents to ticket creation.

  2. **documentation/agent_design.md** — Detailed documentation of each of the 6 agents: CSV Agent, Feedback Classifier, Bug Analyzer, Feature Extractor,
  Ticket Creator, Quality Critic. For each agent, document: purpose, input/output, system prompt summary, LLM vs deterministic, error handling/fallback
  behavior, and which files implement it.

  3. **documentation/langgraph_pipeline.md** — How the LangGraph StateGraph is constructed: the PipelineState TypedDict, all nodes, conditional edge
  routing logic (route_after_classification, route_after_review, route_next_or_end), the batch processing loop pattern, and a visual flow diagram. Include
  code references to src/graph/workflow.py.

  4. **documentation/database_schema.md** — Full SQLite schema documentation for all 3 tables (raw_feedback, tickets, processing_log): column descriptions,
   constraints, relationships, and the query helper functions available in src/db/queries.py with their signatures and usage examples.

  5. **documentation/mcp_server.md** — Documentation of the FastMCP ticket management server: the 3 tools (create_ticket, update_ticket, get_tickets),
  their parameters, return formats, how the server is launched via stdio transport, and how the Ticket Creator agent connects to it as an MCP client.

  6. **documentation/streamlit_ui.md** — Documentation of the 4-page Streamlit UI: Upload & Process (CSV upload, manual input, real-time agent status),
  Dashboard (ticket table, detail view, manual override), Analytics (charts, classification accuracy, confusion matrix), Configuration (thresholds, API key
   status, connection tests). Include screenshots-placeholder sections.

  7. **documentation/observability.md** — How Langfuse tracing is integrated: the tracing.py module (create_trace, create_langfuse_handler, traced_span,
  score_trace), where tracing hooks into each agent, the metrics.py collector, and how to view traces in the Langfuse dashboard.

  8. **documentation/setup_and_usage.md** — Step-by-step setup guide: prerequisites, installing dependencies, configuring .env, initializing the database,
  running the Streamlit app, running tests, processing mock data, and troubleshooting common issues.

  Read every source file before writing. Use code references (file:line) where relevant. Include mermaid diagrams where they help explain flow. Do not
  invent or assume — only document what actually exists in the code.

  ---
  This prompt covers all 8 documentation files and explicitly instructs to read the actual code first before writing. You can paste it into a fresh session where it'll have full context budget.

------------------------------------------

