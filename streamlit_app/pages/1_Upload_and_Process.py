"""Upload & Process page — CSV upload, manual input, real-time processing status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import json
import uuid
import streamlit as st

from src.config import settings
from src.db.database import init_db
from src.agents.csv_agent import ingest_feedback_items
from src.models.schemas import FeedbackItem
from src.utils.csv_parser import detect_csv_type, parse_csv_file
from src.graph.workflow import build_pipeline, create_initial_state

init_db()

st.header("Upload & Process Feedback")

# --- CSV Upload Section ---
st.subheader("Upload CSV File")

col1, col2 = st.columns([3, 1])
with col1:
    uploaded_file = st.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        help="Upload app store reviews or support emails CSV",
    )
with col2:
    source_type_option = st.radio(
        "Source type",
        ["Auto-detect", "App Store Reviews", "Support Emails"],
        index=0,
    )

# --- Manual Input Section ---
st.subheader("Or Submit Manual Feedback")
with st.expander("Submit a single review or feedback"):
    manual_text = st.text_area(
        "Feedback text",
        height=100,
        placeholder="Enter the feedback or review text here...",
    )
    manual_col1, manual_col2, manual_col3 = st.columns(3)
    with manual_col1:
        manual_platform = st.selectbox(
            "Platform", ["Google Play", "App Store", "Email", "Other"]
        )
    with manual_col2:
        manual_rating = st.slider("Rating (optional)", 0, 5, 0, help="0 = no rating")
    with manual_col3:
        manual_subject = st.text_input("Subject (optional)")

    submit_manual = st.button("Submit Manual Feedback")

# --- Processing ---
st.markdown("---")

# Initialize session state for processing
if "processing_status" not in st.session_state:
    st.session_state.processing_status = []
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False


def process_feedback(feedback_items: list[FeedbackItem]):
    """Run the LangGraph pipeline on a list of feedback items."""
    st.session_state.is_processing = True
    st.session_state.processing_status = []

    # Store items in DB and get state dicts
    state_items = ingest_feedback_items(feedback_items)

    if not state_items:
        st.error("No items to process.")
        st.session_state.is_processing = False
        return

    # Status display container
    status_container = st.container()
    progress_bar = st.progress(0, text="Starting pipeline...")

    status_messages = []

    def status_callback(update: dict):
        """Called by each graph node to update real-time status."""
        agent = update.get("agent", "")
        status = update.get("status", "")
        idx = update.get("current_index", 0)
        total = update.get("total_items", 0)

        msg = f"**{agent}** — {status}"

        # Supervisor reasoning (agentic routing decisions)
        reasoning = update.get("supervisor_reasoning", "")
        if reasoning and agent == "supervisor":
            msg += f" | Routing: {reasoning}"

        classification = update.get("classification")
        if classification and agent == "classifier":
            msg += f" | Category: {classification['category']} (confidence: {classification['confidence']:.2f})"

        ticket = update.get("ticket")
        if ticket and agent == "ticket_creator":
            msg += f" | Ticket: {ticket['ticket_id']}"

        review = update.get("quality_review")
        if review and agent == "quality_critic":
            emoji = "Approved" if review["approved"] else "Revision needed"
            msg += f" | Score: {review['score']}/10 — {emoji}"

        status_messages.append(msg)

        # Update progress
        if total > 0:
            progress = min((idx + 1) / total, 1.0)
            progress_bar.progress(progress, text=f"Processing item {idx + 1}/{total}")

    # Build and run pipeline
    try:
        pipeline = build_pipeline(
            status_callback=status_callback,
        )

        initial_state = create_initial_state(state_items)

        with status_container:
            with st.status("Processing feedback...", expanded=True) as status_widget:
                result = pipeline.invoke(initial_state)

                # Display all collected status messages
                for msg in status_messages:
                    st.markdown(msg)

                completed = result.get("completed_tickets", [])
                status_widget.update(
                    label=f"Processing complete! {len(completed)} tickets created.",
                    state="complete",
                )

        progress_bar.progress(1.0, text="Done!")

        # Show summary
        st.success(
            f"Processed {len(state_items)} feedback items. "
            f"Created {len(completed)} tickets: {', '.join(completed)}"
        )

        # Auto-generate output CSV files
        try:
            from src.utils.csv_exporter import export_all_csvs
            csv_paths = export_all_csvs()
            st.info(
                f"Output CSVs generated in `data/output/`: "
                f"{', '.join(p.name for p in csv_paths.values())}"
            )
        except Exception as csv_err:
            st.warning(f"CSV export warning: {csv_err}")

    except Exception as e:
        st.error(f"Pipeline error: {e}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        st.session_state.is_processing = False


# Handle CSV upload
if uploaded_file is not None:
    process_csv = st.button(
        "Process CSV",
        disabled=st.session_state.is_processing,
        type="primary",
    )
    if process_csv:
        file_content = uploaded_file.getvalue().decode("utf-8")

        # Detect or use selected source type
        if source_type_option == "Auto-detect":
            try:
                detected_type = detect_csv_type(file_content)
                st.info(f"Auto-detected CSV type: **{detected_type}**")
            except ValueError as e:
                st.error(str(e))
                st.stop()
        elif source_type_option == "App Store Reviews":
            detected_type = "app_store_review"
        else:
            detected_type = "support_email"

        # Parse CSV
        try:
            items = parse_csv_file(
                file_content, detected_type, source_file=uploaded_file.name
            )
            st.info(f"Parsed **{len(items)}** feedback items from CSV")
            process_feedback(items)
        except Exception as e:
            st.error(f"CSV parsing error: {e}")

# Handle manual submission
if submit_manual and manual_text.strip():
    manual_item = FeedbackItem(
        source_id=f"MANUAL-{uuid.uuid4().hex[:8]}",
        source_type="manual_input",
        content_text=manual_text.strip(),
        subject=manual_subject or None,
        rating=manual_rating if manual_rating > 0 else None,
        platform=manual_platform,
    )
    process_feedback([manual_item])
elif submit_manual and not manual_text.strip():
    st.warning("Please enter some feedback text.")
