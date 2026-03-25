"""Processing metrics tracking for the feedback pipeline."""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessingMetric:
    """A single metric record from one agent processing one feedback item."""

    feedback_id: int
    agent_name: str
    latency_ms: float
    category: str = ""
    status: str = "success"
    error: Optional[str] = None
    quality_score: float = 0.0


class MetricsCollector:
    """Collects and aggregates processing metrics for a batch."""

    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        self.records: list[ProcessingMetric] = []
        self._batch_start = time.perf_counter()

    def record(self, metric: ProcessingMetric) -> None:
        self.records.append(metric)

    def get_summary(self) -> dict:
        """Aggregate metrics into a summary dict for analytics."""
        if not self.records:
            return {
                "batch_id": self.batch_id,
                "total_items": 0,
                "total_duration_ms": 0,
            }

        total_duration = (time.perf_counter() - self._batch_start) * 1000

        # Group by agent
        by_agent: dict[str, list[float]] = {}
        for r in self.records:
            by_agent.setdefault(r.agent_name, []).append(r.latency_ms)

        agent_stats = {}
        for agent, latencies in by_agent.items():
            agent_stats[agent] = {
                "count": len(latencies),
                "avg_ms": round(sum(latencies) / len(latencies), 2),
                "max_ms": round(max(latencies), 2),
                "min_ms": round(min(latencies), 2),
            }

        # Group by category
        by_category: dict[str, int] = {}
        for r in self.records:
            if r.category and r.agent_name == "classifier":
                by_category[r.category] = by_category.get(r.category, 0) + 1

        # Error count
        errors = [r for r in self.records if r.status == "error"]

        # Quality scores
        quality_scores = [
            r.quality_score for r in self.records
            if r.agent_name == "quality_critic" and r.quality_score > 0
        ]
        avg_quality = (
            round(sum(quality_scores) / len(quality_scores), 2)
            if quality_scores
            else 0.0
        )

        return {
            "batch_id": self.batch_id,
            "total_items": len(by_category) if by_category else 0,
            "total_duration_ms": round(total_duration, 2),
            "by_agent": agent_stats,
            "by_category": by_category,
            "error_count": len(errors),
            "avg_quality_score": avg_quality,
        }


class LatencyTimer:
    """Simple context-manager timer that captures elapsed time in ms."""

    def __init__(self):
        self.start_time: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000
