"""Main Streamlit application entry point."""

import sys
from pathlib import Path

# Add project root to path so src imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(
    page_title="Feedback Analysis System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Intelligent User Feedback Analysis System")
st.markdown(
    "Multi-agent AI system for automated feedback processing and ticket creation"
)

# Initialize database on first load
if "db_initialized" not in st.session_state:
    from src.db.database import init_db
    init_db()
    st.session_state.db_initialized = True

# Sidebar
st.sidebar.markdown("---")
st.sidebar.markdown("**System Info**")

from src.config import settings
st.sidebar.text(f"Model: {settings.openai_model}")
st.sidebar.text(f"Confidence threshold: {settings.classification_confidence_threshold}")
st.sidebar.text(f"Quality threshold: {settings.quality_auto_approve_threshold}")

# Summary cards on home page
from src.db.database import get_conn

conn = get_conn()
try:
    feedback_count = conn.execute("SELECT COUNT(*) FROM raw_feedback").fetchone()[0]
    ticket_count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    approved_count = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE quality_status = 'approved'"
    ).fetchone()[0]
    avg_quality = conn.execute(
        "SELECT AVG(quality_score) FROM tickets WHERE quality_score IS NOT NULL"
    ).fetchone()[0]
finally:
    conn.close()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Feedback", feedback_count)
col2.metric("Tickets Created", ticket_count)
col3.metric("Tickets Approved", approved_count)
col4.metric("Avg Quality Score", f"{avg_quality:.1f}" if avg_quality is not None else "N/A")

st.markdown("---")
st.markdown(
    "Use the **sidebar** to navigate between pages:\n"
    "- **Upload & Process**: Upload CSV files or submit manual feedback\n"
    "- **Dashboard**: View and manage generated tickets\n"
    "- **Analytics**: Processing statistics and classification accuracy\n"
    "- **Configuration**: Adjust thresholds and system settings"
)
