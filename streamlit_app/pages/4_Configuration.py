"""Configuration page — thresholds, API key status, settings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from src.config import settings

st.header("Configuration")

# --- API Key Status ---
st.subheader("API Key Status")

col1, col2 = st.columns(2)
with col1:
    openai_key = settings.openai_api_key
    if openai_key:
        masked = openai_key[:8] + "..." + openai_key[-4:] if len(openai_key) > 12 else "****"
        st.success(f"OpenAI API Key: `{masked}`")
    else:
        st.error("OpenAI API Key: **Not set**. Add `OPENAI_API_KEY` to `.env` file.")

with col2:
    langfuse_key = settings.langfuse_public_key
    if langfuse_key:
        masked = langfuse_key[:8] + "..." + langfuse_key[-4:] if len(langfuse_key) > 12 else "****"
        st.success(f"Langfuse Public Key: `{masked}`")
    else:
        st.warning("Langfuse Key: **Not set**. Tracing disabled. Add keys to `.env` file.")

# --- Connection Test ---
st.subheader("Connection Test")
test_col1, test_col2 = st.columns(2)
with test_col1:
    if st.button("Test OpenAI Connection"):
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )
            response = llm.invoke("Say 'OK' in one word.")
            st.success(f"OpenAI connected! Response: {response.content}")
        except Exception as e:
            st.error(f"OpenAI connection failed: {e}")

with test_col2:
    if st.button("Test Langfuse Connection"):
        try:
            from src.observability.tracing import get_langfuse
            lf = get_langfuse()
            if lf:
                st.success("Langfuse client initialized successfully!")
            else:
                st.warning("Langfuse client could not be initialized. Check keys.")
        except Exception as e:
            st.error(f"Langfuse connection failed: {e}")

st.markdown("---")

# --- Classification Settings ---
st.subheader("Classification Settings")

confidence_threshold = st.slider(
    "Confidence Threshold",
    min_value=0.5,
    max_value=1.0,
    value=settings.classification_confidence_threshold,
    step=0.05,
    help="Minimum confidence score for a classification to be accepted. "
         "Below this threshold, a warning is logged but processing continues.",
)

st.markdown("---")

# --- Quality Settings ---
st.subheader("Quality Settings")

quality_threshold = st.slider(
    "Auto-Approve Threshold",
    min_value=5.0,
    max_value=10.0,
    value=settings.quality_auto_approve_threshold,
    step=0.5,
    help="Minimum quality score for a ticket to be automatically approved. "
         "Tickets below this score are sent back for revision.",
)

max_revisions = st.number_input(
    "Maximum Revisions",
    min_value=1,
    max_value=5,
    value=settings.max_revision_count,
    help="Maximum number of revision attempts before force-approving a ticket.",
)

st.markdown("---")

# --- Agentic Pipeline Settings ---
st.subheader("Agentic Pipeline Settings")

max_iterations = st.number_input(
    "Max Agent Iterations",
    min_value=2,
    max_value=10,
    value=settings.max_agent_iterations,
    help="Maximum ReAct loop iterations per agent. Higher = more autonomous but slower/costlier.",
)

st.info(
    "This system uses a **hybrid supervisor + ReAct agent** architecture. "
    "The LLM supervisor routes feedback between specialist agents, and each agent "
    "autonomously calls tools (MCP, database) via tool-use."
)

st.markdown("---")

# --- Model Settings ---
st.subheader("Model Settings")

st.text_input("Model", value=settings.openai_model, disabled=True)

temperature = st.slider(
    "Temperature",
    min_value=0.0,
    max_value=1.0,
    value=settings.openai_temperature,
    step=0.1,
    help="LLM temperature for response generation. Lower = more deterministic.",
)

st.markdown("---")

# Save settings to session state for use by the pipeline
if st.button("Apply Settings", type="primary"):
    st.session_state["config_overrides"] = {
        "confidence_threshold": confidence_threshold,
        "quality_threshold": quality_threshold,
        "max_revisions": max_revisions,
        "temperature": temperature,
    }
    st.success(
        "Settings applied for this session. "
        "To persist, update the `.env` file."
    )

st.markdown("---")
st.markdown(
    "**Note:** Settings changed here apply only to the current session. "
    "For persistent changes, update the `.env` file in the project root."
)
