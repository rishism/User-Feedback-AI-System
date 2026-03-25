"""Analytics page — charts, metrics, classification accuracy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import csv
import io
import streamlit as st
import pandas as pd
import plotly.express as px

from src.db.database import init_db, get_conn

init_db()

st.header("Analytics & Metrics")

conn = get_conn()
try:
    # --- Summary Metrics ---
    total_feedback = conn.execute("SELECT COUNT(*) FROM raw_feedback").fetchone()[0]
    total_tickets = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    avg_quality = conn.execute(
        "SELECT AVG(quality_score) FROM tickets WHERE quality_score IS NOT NULL"
    ).fetchone()[0]
    error_count = conn.execute(
        "SELECT COUNT(*) FROM processing_log WHERE status = 'error'"
    ).fetchone()[0]
    approved_count = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE quality_status = 'approved'"
    ).fetchone()[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Processed", total_feedback)
    col2.metric("Tickets Created", total_tickets)
    col3.metric("Avg Quality Score", f"{avg_quality:.1f}" if avg_quality is not None else "N/A")
    col4.metric("Errors", error_count)

    st.markdown("---")

    # --- Classification Distribution ---
    st.subheader("Classification Distribution")
    cat_rows = conn.execute(
        "SELECT category, COUNT(*) as count FROM tickets GROUP BY category ORDER BY count DESC"
    ).fetchall()

    if cat_rows:
        cat_df = pd.DataFrame([dict(r) for r in cat_rows])
        col_chart, col_pie = st.columns(2)
        with col_chart:
            fig_bar = px.bar(
                cat_df, x="category", y="count",
                title="Tickets by Category",
                color="category",
            )
            st.plotly_chart(fig_bar, width="stretch")
        with col_pie:
            fig_pie = px.pie(
                cat_df, names="category", values="count",
                title="Category Distribution",
            )
            st.plotly_chart(fig_pie, width="stretch")
    else:
        st.info("No tickets yet. Process some feedback first.")

    # --- Priority Distribution ---
    st.subheader("Priority Distribution")
    pri_rows = conn.execute(
        "SELECT priority, COUNT(*) as count FROM tickets GROUP BY priority ORDER BY count DESC"
    ).fetchall()

    if pri_rows:
        pri_df = pd.DataFrame([dict(r) for r in pri_rows])
        fig_pri = px.bar(
            pri_df, x="priority", y="count",
            title="Tickets by Priority",
            color="priority",
            color_discrete_map={
                "Critical": "#dc3545",
                "High": "#fd7e14",
                "Medium": "#ffc107",
                "Low": "#28a745",
            },
        )
        st.plotly_chart(fig_pri, width="stretch")
    else:
        st.info("No priority data available yet.")

    # --- Quality Score Distribution ---
    st.subheader("Quality Score Distribution")
    quality_rows = conn.execute(
        "SELECT quality_score FROM tickets WHERE quality_score IS NOT NULL"
    ).fetchall()

    if quality_rows:
        quality_df = pd.DataFrame([dict(r) for r in quality_rows])
        fig_quality = px.histogram(
            quality_df, x="quality_score",
            nbins=10,
            title="Quality Score Distribution",
            labels={"quality_score": "Quality Score"},
        )
        fig_quality.add_vline(x=7.0, line_dash="dash", line_color="green",
                              annotation_text="Approval threshold")
        st.plotly_chart(fig_quality, width="stretch")
    else:
        st.info("No quality score data available yet.")

    # --- Agent Processing Latency ---
    st.subheader("Agent Processing Latency")
    latency_rows = conn.execute(
        "SELECT agent_name, AVG(latency_ms) as avg_ms, COUNT(*) as count "
        "FROM processing_log WHERE latency_ms IS NOT NULL "
        "GROUP BY agent_name ORDER BY avg_ms DESC"
    ).fetchall()

    if latency_rows:
        latency_df = pd.DataFrame([dict(r) for r in latency_rows])
        fig_latency = px.bar(
            latency_df, x="agent_name", y="avg_ms",
            title="Average Latency by Agent (ms)",
            labels={"agent_name": "Agent", "avg_ms": "Avg Latency (ms)"},
        )
        st.plotly_chart(fig_latency, width="stretch")
    else:
        st.info("No agent latency data available yet.")

    # --- Classification Accuracy vs Expected ---
    st.subheader("Classification Accuracy")
    st.markdown("Compare against `expected_classifications.csv` ground truth:")

    expected_path = Path(__file__).resolve().parent.parent.parent / "data" / "mock" / "expected_classifications.csv"
    if expected_path.exists():
        expected_df = pd.read_csv(expected_path)

        # Join with actual tickets
        ticket_rows = conn.execute(
            """SELECT t.category as predicted, t.priority as predicted_priority,
                      f.source_id, f.source_type
               FROM tickets t
               JOIN raw_feedback f ON t.feedback_id = f.id"""
        ).fetchall()

        if ticket_rows:
            actual_df = pd.DataFrame([dict(r) for r in ticket_rows])

            # Merge on source_id and source_type
            merged = pd.merge(
                expected_df,
                actual_df,
                left_on=["source_id", "source_type"],
                right_on=["source_id", "source_type"],
                how="inner",
            )

            if not merged.empty:
                # Category accuracy
                merged["category_match"] = merged["category"] == merged["predicted"]
                accuracy = merged["category_match"].mean() * 100

                st.metric("Category Classification Accuracy", f"{accuracy:.1f}%")

                # Confusion matrix
                try:
                    from sklearn.metrics import confusion_matrix
                    categories = sorted(set(merged["category"].tolist() + merged["predicted"].tolist()))
                    cm = confusion_matrix(
                        merged["category"], merged["predicted"], labels=categories
                    )
                    cm_df = pd.DataFrame(cm, index=categories, columns=categories)
                    st.markdown("**Confusion Matrix** (rows=expected, cols=predicted)")
                    st.dataframe(cm_df, width="stretch")
                except Exception:
                    # sklearn not available or error — show simple comparison
                    st.dataframe(
                        merged[["source_id", "category", "predicted", "category_match"]],
                        width="stretch",
                    )
            else:
                st.info("No matching tickets found for accuracy comparison.")
        else:
            st.info("No tickets generated yet.")
    else:
        st.info(
            "Upload `expected_classifications.csv` to `data/mock/` for accuracy analysis."
        )

except Exception as e:
    st.error(f"Error loading analytics: {e}")
    import traceback
    st.code(traceback.format_exc())
finally:
    conn.close()
