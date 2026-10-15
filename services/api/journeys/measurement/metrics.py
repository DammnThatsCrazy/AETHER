"""Measurement service metrics — canonical activity, journey compilation, cross-rail transitions."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

from shared.logger.logger import metrics as _metrics


class CanonicalActivityMetrics:
    """Metrics for canonical_activity ledger ingestion."""

    def record_ingested(self, tenant_id: str, family: str) -> None:
        _metrics.increment(
            "canonical_activities_ingested_total",
            labels={"tenant_id": tenant_id, "family": family},
        )

    def record_projection_error(self, tenant_id: str, family: str) -> None:
        _metrics.increment(
            "canonical_activities_projected_errors_total",
            labels={"tenant_id": tenant_id, "family": family},
        )

    def record_status_update(self, tenant_id: str, new_status: str) -> None:
        _metrics.increment(
            "canonical_activity_status_updates_total",
            labels={"tenant_id": tenant_id, "status": new_status},
        )


class JourneyCompilerMetrics:
    """Metrics for JourneyCompiler v2.0."""

    @contextmanager
    def timed_compile(self, tenant_id: str) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            _metrics.histogram(
                "journey_compile_duration_seconds",
                elapsed,
                labels={"tenant_id": tenant_id},
            )

    def record_compile_error(self, reason: str) -> None:
        _metrics.increment(
            "journey_compile_errors_total",
            labels={"reason": reason},
        )

    def record_steps_per_journey(self, step_count: int) -> None:
        _metrics.histogram("journey_steps_per_journey", step_count)

    def record_rebuild_queued(self) -> None:
        _metrics.increment("journey_rebuild_queue_depth")

    def record_rebuild_dequeued(self) -> None:
        _metrics.decrement("journey_rebuild_queue_depth")


class CrossRailMetrics:
    """Metrics for cross-rail transition tracking and Web3 finality events."""

    def record_transition(self, from_family: str, to_family: str) -> None:
        _metrics.increment(
            "cross_rail_transition_count",
            labels={"from_family": from_family, "to_family": to_family},
        )

    def record_reorg_correction(self, tenant_id: str) -> None:
        _metrics.increment(
            "web3_reorg_corrections_total",
            labels={"tenant_id": tenant_id},
        )

    def record_late_event(self, tenant_id: str, family: str) -> None:
        _metrics.increment(
            "late_event_insertions_total",
            labels={"tenant_id": tenant_id, "family": family},
        )


# Module-level singletons — import these in compiler, repo, and projector base.
canonical_activity_metrics = CanonicalActivityMetrics()
journey_compiler_metrics = JourneyCompilerMetrics()
cross_rail_metrics = CrossRailMetrics()
