# Agent Design

## Agent Factory Pattern

Five of the six agents (all except the CSV Agent) use a **factory pattern**: a function `create_*_node(llm)` that accepts a `ChatOpenAI` instance and returns a closure. This closure captures the shared LLM and acts as the LangGraph node function.

```python
# src/graph/workflow.py:111-116
classify = create_classify_node(llm)
bug_analyze = create_bug_analyze_node(llm)
feature_extract = create_feature_extract_node(llm)
create_ticket = create_ticket_node(llm, use_mcp=use_mcp)
quality_review = create_quality_review_node(llm)
```

The single `ChatOpenAI` instance is created in `build_pipeline()` (`workflow.py:105-109`) with the configured API key, model (default `gpt-5.4`), and temperature (default `0.1`).

The CSV Agent's `ingest_node` is a regular function (no factory) since it doesn't use an LLM (`csv_agent.py:68`).

## Agent Summary

| Agent | File | LLM? | Input | Output |
|-------|------|------|-------|--------|
| CSV Agent | `src/agents/csv_agent.py` | No | `PipelineState` (feedback_items list) | `current_item`, reset fields |
| Classifier | `src/agents/classifier.py` | Yes | `current_item` text/rating/platform | `classification` dict |
| Bug Analyzer | `src/agents/bug_analyzer.py` | Yes | `current_item` (Bug feedback) | `analysis` with `technical_details` |
| Feature Extractor | `src/agents/feature_extractor.py` | Yes | `current_item` (Feature Request) | `analysis` with `feature_details` |
| Ticket Creator | `src/agents/ticket_creator.py` | Yes | `classification` + `analysis` + `quality_review` | `ticket` dict |
| Quality Critic | `src/agents/quality_critic.py` | Yes | `ticket` + `classification` + `current_item` | `quality_review` dict |

---

## 1. CSV Agent (Ingest)

**File:** `src/agents/csv_agent.py`

### Purpose

Parses uploaded CSV files, stores raw feedback in the SQLite database, and manages item selection during batch processing. This is the only **deterministic** agent — it uses no LLM.

### I/O Contract

**`ingest_feedback_items(items, conn=None)`** (`csv_agent.py:16-65`)
- **Input:** `list[FeedbackItem]` (Pydantic models from CSV parsing)
- **Output:** `list[FeedbackItemState]` (TypedDicts for the LangGraph pipeline)
- **Side effects:** Inserts each item into `raw_feedback` table, logs to `processing_log`

**`ingest_node(state)`** (`csv_agent.py:68-95`)
- **Input:** `PipelineState` with `feedback_items` list and `current_index`
- **Output:**
  ```python
  {
      "current_item": items[current_index],  # The item to process
      "current_agent": "ingest",
      "status": "ingesting",
      "classification": None,  # Reset for new item
      "analysis": None,
      "ticket": None,
      "quality_review": None,
      "revision_count": 0,
  }
  ```

### Implementation Details

- Called once per feedback item in the batch loop
- Resets all intermediate state fields (`classification`, `analysis`, `ticket`, `quality_review`, `revision_count`) to `None`/`0` — ensuring each item starts with a clean slate (`csv_agent.py:90-94`)
- Handles out-of-bounds index by returning `current_item: None` with `status: "done"` (`csv_agent.py:73-78`)
- `ingest_feedback_items()` calls `init_db()` to ensure tables exist (`csv_agent.py:21`)

### Error Handling

- Duplicate feedback items are silently handled by `INSERT OR IGNORE` in `insert_feedback()` — returns the existing ID

---

## 2. Feedback Classifier

**File:** `src/agents/classifier.py`

### Purpose

Classifies each feedback item into exactly one of 5 categories with a confidence score and reasoning.

### I/O Contract

- **Input:** `current_item` from state (content_text, rating, platform, source_type, subject)
- **Output:**
  ```python
  {
      "classification": {
          "category": "Bug",           # Bug | Feature Request | Praise | Complaint | Spam
          "confidence": 0.92,          # 0.0-1.0
          "reasoning": "User reports app crash on login page"
      },
      "current_agent": "classifier",
      "status": "classifying",
  }
  ```

### System Prompt Summary (`classifier.py:16-37`)

The classifier acts as an expert feedback classifier for a productivity app called **TaskPro**. Key guidelines:

- **Bug:** Technical issues, crashes, errors, broken features, data loss, performance problems
- **Feature Request:** Suggestions for new features, improvements, enhancements
- **Praise:** Positive feedback, compliments, satisfaction
- **Complaint:** Dissatisfaction about non-technical issues (pricing, customer service, UX)
- **Spam:** Promotional content, irrelevant text, gibberish

The rating serves as a secondary signal: 1-2 stars correlates with bugs/complaints, 4-5 with praise. Specific technical failures are classified as Bug even with a complaining tone.

### Implementation Details

- The user message is built from available fields: subject, content_text, rating, platform, source_type (`classifier.py:40-57`)
- Uses `SystemMessage` + `HumanMessage` pattern (`classifier.py:71-74`)
- Measures latency via `LatencyTimer` (`classifier.py:70`)
- Logs to DB: calls `update_feedback_status(id, "classified")` and `log_processing()` with latency and trace_id (`classifier.py:93-103`)

### Error Handling (`classifier.py:76-84`)

On JSON parse failure, defaults to:
```python
{"category": "Complaint", "confidence": 0.5, "reasoning": "Failed to parse LLM response, defaulting to Complaint"}
```

---

## 3. Bug Analyzer

**File:** `src/agents/bug_analyzer.py`

### Purpose

Extracts structured technical details from feedback classified as a Bug: severity, affected component, reproduction steps, expected vs actual behavior, and engineering recommendations.

### I/O Contract

- **Input:** `current_item` (content_text, rating, platform, app_version)
- **Output:**
  ```python
  {
      "analysis": {
          "technical_details": {
              "severity": "Major",
              "affected_component": "Login",
              "platform_details": {"device": "iPhone 15", "os": "iOS 18.2", "app_version": "3.2.1"},
              "steps_to_reproduce": ["1. Open app", "2. Tap login", "3. App crashes"],
              "expected_behavior": "User should be logged in",
              "actual_behavior": "App crashes with no error message",
          },
          "feature_details": None,
          "suggested_title": "[Bug] App crashes on login",
          "suggested_priority": "High",
          "suggested_actions": ["Investigate crash logs", "Test on iOS 18.2"],
      },
      "current_agent": "bug_analyzer",
      "status": "analyzing",
  }
  ```

### System Prompt Summary (`bug_analyzer.py:15-39`)

Acts as a **senior QA engineer** analyzing bug reports. Extracts 8 fields:

1. **Severity:** Critical (app unusable, data loss) | Major (key feature broken) | Minor (workaround exists) | Cosmetic (visual only)
2. **Affected component:** Login, Sync, UI, Notifications, Dashboard, Settings, Tasks, Search, Performance, etc.
3. **Platform details:** device model, OS version, app version
4. **Steps to reproduce:** numbered steps inferred from feedback text
5. **Expected vs actual behavior**
6. **Suggested title:** under 80 characters
7. **Suggested priority:** Critical | High | Medium | Low
8. **Suggested actions:** 2-3 concrete next steps

### Error Handling (`bug_analyzer.py:64-78`)

On JSON parse failure, defaults to:
- `severity: "Major"`, `affected_component: "Unknown"`, `suggested_priority: "Medium"`
- Steps: `["Unable to parse from feedback"]`
- Actual behavior: first 200 characters of content_text

---

## 4. Feature Extractor

**File:** `src/agents/feature_extractor.py`

### Purpose

Analyzes feedback classified as Feature Request: identifies the feature, assesses user impact and demand signal, and recommends actions for the product team.

### I/O Contract

- **Input:** `current_item` (content_text, rating, platform)
- **Output:**
  ```python
  {
      "analysis": {
          "technical_details": None,
          "feature_details": {
              "feature_name": "Dark Mode Support",
              "description": "User wants a dark mode option...",
              "user_impact": "High",
              "demand_signal": "Strong",
              "existing_alternatives": "None mentioned",
          },
          "suggested_title": "[Feature] Add dark mode support",
          "suggested_priority": "High",
          "suggested_actions": ["Survey user base", "Create mockups"],
      },
      "current_agent": "feature_extractor",
      "status": "analyzing",
  }
  ```

### System Prompt Summary (`feature_extractor.py:15-38`)

Acts as a **product manager** analyzing feature requests. Extracts 8 fields:

1. **Feature name:** concise 3-5 word name
2. **Description:** what the user wants and why (2-3 sentences)
3. **User impact:** High (many users, core workflow) | Medium (moderate benefit) | Low (niche/edge case)
4. **Demand signal:** Strong (urgent, explicit request) | Moderate (suggestion) | Weak (implied, vague)
5. **Existing alternatives:** workarounds mentioned
6. **Suggested title:** under 80 characters
7. **Suggested priority:** High | Medium | Low
8. **Suggested actions:** 2-3 next steps for the product team

### Error Handling (`feature_extractor.py:63-74`)

On JSON parse failure, defaults to:
- `feature_name: "Unknown Feature"`, `user_impact: "Medium"`, `demand_signal: "Moderate"`, `suggested_priority: "Medium"`
- Description: first 200 characters of content_text

---

## 5. Ticket Creator

**File:** `src/agents/ticket_creator.py`

### Purpose

Generates structured, well-formatted tickets from classified and analyzed feedback. Supports two storage paths: direct database insert or MCP server.

### I/O Contract

- **Input:** `current_item` + `classification` + `analysis` (optional) + `quality_review` (if revision)
- **Output:**
  ```python
  {
      "ticket": {
          "ticket_id": "TKT-20260323-001",
          "feedback_id": 42,
          "category": "Bug",
          "confidence": 0.92,
          "title": "[Bug] App crashes on login page",
          "description": "## Summary\nApp crashes immediately...\n## Steps to Reproduce\n...",
          "priority": "High",
      },
      "current_agent": "ticket_creator",
      "status": "ticketing",
  }
  ```

### System Prompt Summary (`ticket_creator.py:22-42`)

Acts as a **technical writer**. Requirements for ticket generation:

- **Title:** Clear, actionable, under 80 chars. Format: `[Category] Brief description`
- **Description:** Structured with sections depending on category:
  - Bugs: Summary, Steps to Reproduce, Expected Behavior, Actual Behavior, Environment
  - Feature Requests: Summary, User Need, Proposed Solution, Impact Assessment
  - Praise: Key Positive Points, Areas Highlighted
  - Complaints: Issue Description, User Impact, Suggested Resolution
  - Spam: Reason for Classification
- **Priority:** Based on severity (bugs), impact (features), or Low (praise/spam)

### Revision Context

When this is a revision attempt (quality_review exists and `approved=False`), the prompt includes the critic's feedback (`ticket_creator.py:72-81`):
- Quality score
- Quality notes
- Revision suggestions

This allows the LLM to specifically address the critic's concerns.

### MCP Integration

The agent supports two ticket storage paths (`ticket_creator.py:134-160`):

- **Direct DB (default):** Calls `insert_ticket()` from `queries.py`
- **MCP server (`use_mcp=True`):** Calls `_create_via_mcp()` (`ticket_creator.py:196-216`), which:
  1. Resolves the MCP server path to `src/mcp_server/server.py`
  2. Creates an async `fastmcp.Client` with stdio transport
  3. Calls the `create_ticket` tool with all ticket parameters
  4. Bridges async/sync via `ThreadPoolExecutor` + `asyncio.run`

### Error Handling (`ticket_creator.py:111-117`)

On JSON parse failure, defaults to:
- Title: `[{category}] {first 60 chars of content}`
- Description: raw content text
- Priority: from analysis `suggested_priority` or `"Medium"`

---

## 6. Quality Critic

**File:** `src/agents/quality_critic.py`

### Purpose

Reviews generated tickets for completeness, accuracy, and actionability. Scores each ticket 0-10 across 5 criteria and decides whether to approve or request revision.

### I/O Contract

- **Input:** `current_item` + `classification` + `ticket`
- **Output:**
  ```python
  {
      "quality_review": {
          "score": 8.5,
          "breakdown": {
              "title_clarity": 2,
              "description_completeness": 3,
              "priority_accuracy": 1,
              "technical_accuracy": 2,
              "actionability": 0.5,
          },
          "approved": True,
          "notes": "Well-structured ticket with clear reproduction steps.",
          "revision_suggestions": [],
      },
      "revision_count": 0,  # incremented if not approved
      "current_agent": "quality_critic",
      "status": "reviewing",
  }
  ```

### Scoring Criteria (`quality_critic.py:16-44`)

Acts as a **senior engineering manager** evaluating tickets on 5 criteria:

| Criterion | Max Score | What It Measures |
|-----------|-----------|-----------------|
| Title clarity | 0-2 | Specific, actionable, correctly prefixed with category? |
| Description completeness | 0-3 | Enough context? Bug: repro steps, environment? Feature: user need, solution? |
| Priority accuracy | 0-2 | Priority matches content severity/impact? |
| Technical accuracy | 0-2 | Technical details reasonable and consistent with feedback? |
| Actionability | 0-1 | Can an engineer pick this up and start immediately? |

**Total: 0-10 points.**

### Auto-Approve Logic (`quality_critic.py:87-89`)

The code **overrides the LLM's `approved` field** using the configuration threshold:

```python
approved = score >= settings.quality_auto_approve_threshold  # default 7.0
```

This ensures consistent approval decisions regardless of the LLM's own judgment.

### Implementation Details

- Updates the ticket in DB with quality info: `quality_score`, `quality_notes`, `quality_status` (`quality_critic.py:99-106`)
- Updates feedback status to `"reviewed"` (`quality_critic.py:108`)
- If not approved: increments `revision_count` (`quality_critic.py:121-123`)
- The routing function `route_after_review()` (`workflow.py:39-44`) then decides whether to send back for revision or finalize

### Error Handling (`quality_critic.py:77-85`)

On JSON parse failure, auto-approves with:
- `score: 7.0`, `approved: True`, `notes: "Auto-approved due to parse error"`, `revision_suggestions: []`

---

## Shared Patterns

All LLM-based agents share these patterns:

1. **Message format:** `[SystemMessage(PROMPT), HumanMessage(user_content)]` from `langchain_core.messages`
2. **Latency tracking:** `with LatencyTimer() as timer:` context manager captures `timer.elapsed_ms`
3. **DB logging:** Every agent calls `update_feedback_status()` and `log_processing()` with agent name, action, status, latency, and trace_id
4. **JSON parsing with fallback:** All wrap `json.loads(response.content)` in try/except with sensible defaults
5. **Trace correlation:** All pass `state.get("trace_id")` to `log_processing()` for Langfuse correlation

---

## Related Documentation

- [LangGraph Pipeline](langgraph_pipeline.md) — How agents connect as nodes
- [Observability](observability.md) — Tracing and metrics integration
- [MCP Server](mcp_server.md) — The MCP ticket creation path
- [Database Schema](database_schema.md) — Tables written to by agents
