"""Dashboard page — view tickets, details, manual override."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd

from src.db.database import init_db, get_conn
from src.db.queries import get_tickets, get_ticket_by_id, update_ticket, get_feedback_by_id

init_db()

st.header("Tickets Dashboard")

# --- Tab navigation ---
tab_all, tab_bugs, tab_features, tab_other, tab_review = st.tabs(
    ["All Tickets", "Bugs", "Feature Requests", "Other", "Needs Review"]
)


def display_ticket_table(tickets: list[dict], key_suffix: str = ""):
    """Display a table of tickets with expandable details."""
    if not tickets:
        st.info("No tickets found.")
        return

    # Prepare DataFrame
    df = pd.DataFrame(tickets)
    display_cols = [
        "ticket_id", "title", "category", "priority",
        "quality_score", "quality_status",
    ]
    available_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[available_cols],
        width="stretch",
        hide_index=True,
    )

    # Expandable detail view
    for ticket in tickets:
        with st.expander(f"{ticket['ticket_id']}: {ticket['title']}"):
            col1, col2, col3 = st.columns(3)
            col1.markdown(f"**Category:** {ticket['category']}")
            col2.markdown(f"**Priority:** {ticket['priority']}")
            col3.markdown(
                f"**Quality:** {ticket.get('quality_score', 'N/A')}/10 "
                f"({ticket.get('quality_status', 'pending')})"
            )

            st.markdown("**Description:**")
            st.text(ticket["description"])

            if ticket.get("technical_details"):
                st.markdown("**Technical Details:**")
                st.json(ticket["technical_details"])

            if ticket.get("feature_details"):
                st.markdown("**Feature Details:**")
                st.json(ticket["feature_details"])

            if ticket.get("quality_notes"):
                st.markdown(f"**Quality Notes:** {ticket['quality_notes']}")

            # Traceability: show original feedback
            feedback = get_feedback_by_id(ticket["feedback_id"])
            if feedback:
                st.markdown("**Original Feedback:**")
                st.text(feedback["content_text"])

            # Manual override section
            st.markdown("---")
            st.markdown("**Manual Override**")
            edit_col1, edit_col2 = st.columns(2)
            with edit_col1:
                new_title = st.text_input(
                    "Edit title",
                    value=ticket["title"],
                    key=f"title_{ticket['ticket_id']}_{key_suffix}",
                )
                new_priority = st.selectbox(
                    "Edit priority",
                    ["Critical", "High", "Medium", "Low"],
                    index=["Critical", "High", "Medium", "Low"].index(ticket["priority"]),
                    key=f"priority_{ticket['ticket_id']}_{key_suffix}",
                )
            with edit_col2:
                action_col1, action_col2, action_col3 = st.columns(3)
                with action_col1:
                    if st.button("Save", key=f"save_{ticket['ticket_id']}_{key_suffix}"):
                        update_ticket(
                            ticket["ticket_id"],
                            title=new_title,
                            priority=new_priority,
                            manually_edited=1,
                            edited_by="streamlit_user",
                        )
                        st.success("Ticket updated!")
                        st.rerun()
                with action_col2:
                    if st.button("Approve", key=f"approve_{ticket['ticket_id']}_{key_suffix}"):
                        update_ticket(
                            ticket["ticket_id"],
                            quality_status="approved",
                            manually_edited=1,
                            edited_by="streamlit_user",
                        )
                        st.success("Ticket approved!")
                        st.rerun()
                with action_col3:
                    if st.button("Reject", key=f"reject_{ticket['ticket_id']}_{key_suffix}"):
                        update_ticket(
                            ticket["ticket_id"],
                            quality_status="revision_needed",
                            manually_edited=1,
                            edited_by="streamlit_user",
                        )
                        st.warning("Ticket marked for revision.")
                        st.rerun()


with tab_all:
    all_tickets = get_tickets(limit=100)
    display_ticket_table(all_tickets, "all")

with tab_bugs:
    bug_tickets = get_tickets(category="Bug", limit=100)
    display_ticket_table(bug_tickets, "bugs")

with tab_features:
    feature_tickets = get_tickets(category="Feature Request", limit=100)
    display_ticket_table(feature_tickets, "features")

with tab_other:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE category NOT IN ('Bug', 'Feature Request') "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        other_tickets = [dict(r) for r in rows]
    finally:
        conn.close()
    display_ticket_table(other_tickets, "other")

with tab_review:
    review_tickets = get_tickets(quality_status="revision_needed", limit=100)
    pending_tickets = get_tickets(quality_status="pending", limit=100)
    display_ticket_table(review_tickets + pending_tickets, "review")

