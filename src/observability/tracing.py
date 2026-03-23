"""Langfuse observability integration for the feedback pipeline."""

import logging
from contextlib import contextmanager
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)

# Lazy-initialized Langfuse client
_langfuse_client = None


def get_langfuse():
    """Get or create the singleton Langfuse client."""
    global _langfuse_client
    if _langfuse_client is None:
        try:
            from langfuse import Langfuse

            _langfuse_client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            logger.info("Langfuse client initialized")
        except Exception as e:
            logger.warning(f"Langfuse initialization failed: {e}. Tracing disabled.")
            _langfuse_client = None
    return _langfuse_client


def create_langfuse_handler(
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """Create a LangChain CallbackHandler for Langfuse tracing.

    This handler is passed to LLM calls via config={"callbacks": [handler]}
    to automatically trace all LangChain/LangGraph operations.
    """
    try:
        from langfuse.langchain import CallbackHandler

        kwargs = {}
        if trace_id:
            kwargs["trace_id"] = trace_id
        if session_id:
            kwargs["session_id"] = session_id
        if user_id:
            kwargs["user_id"] = user_id

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            **kwargs,
        )
        return handler
    except Exception as e:
        logger.warning(f"Failed to create Langfuse handler: {e}")
        return None


def create_trace(
    name: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    input_data: Optional[dict] = None,
    metadata: Optional[dict] = None,
):
    """Create a new root trace in Langfuse."""
    langfuse = get_langfuse()
    if langfuse is None:
        return None
    try:
        trace = langfuse.trace(
            name=name,
            session_id=session_id,
            user_id=user_id,
            input=input_data,
            metadata=metadata,
        )
        return trace
    except Exception as e:
        logger.warning(f"Failed to create trace: {e}")
        return None


@contextmanager
def traced_span(trace, name: str, input_data: Optional[dict] = None):
    """Context manager to create a timed span within a trace.

    Usage:
        with traced_span(trace, "csv_agent", {"file": "reviews.csv"}) as span:
            # do work
            span.update(output={"items_parsed": 25})
    """
    if trace is None:
        yield None
        return

    import time

    span = None
    start = time.perf_counter()
    try:
        span = trace.span(name=name, input=input_data)
        yield span
    except Exception as e:
        if span:
            span.update(
                output={"error": str(e)},
                level="ERROR",
            )
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if span:
            span.update(
                metadata={"latency_ms": round(elapsed_ms, 2)},
            )


def score_trace(
    trace,
    name: str,
    value: float,
    comment: Optional[str] = None,
) -> None:
    """Attach a score to a trace (e.g., classification confidence, quality score)."""
    if trace is None:
        return
    try:
        trace.score(name=name, value=value, comment=comment)
    except Exception as e:
        logger.warning(f"Failed to score trace: {e}")


def flush() -> None:
    """Flush any pending Langfuse events."""
    langfuse = get_langfuse()
    if langfuse:
        try:
            langfuse.flush()
        except Exception:
            pass
