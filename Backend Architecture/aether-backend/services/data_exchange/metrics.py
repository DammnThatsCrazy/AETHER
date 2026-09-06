"""Data Exchange Plane — ops / hardening observability metric set (M7).

A single, named surface for every counter the M7 ops milestone emits — the
expire / reconcile / cleanup sweeps and the egress-finalization bridge — so
metric names stay stable and are discoverable from one module.  Everything
delegates to the shared collector (``shared.logger.logger.metrics``); there is
no independent state here.

Design (mirrors ``services/traffic/metrics.py``):

- ``METRIC_NAMES`` is the authoritative, test-asserted name list.  The shared
  ``MetricsCollector`` auto-registers counters on first use, so **no repo-wide
  registry allowlist needs editing** — ``register_metrics()`` is therefore a
  no-op that exists so lifespan wiring can *call* one seam regardless of the
  collector's registration model.  If a repo-wide meter-name allowlist is ever
  introduced, ``METRIC_NAMES`` is the exact set the coordinator must register.
- Label cardinality is bounded to canonical vocabulary (bounded dispositions —
  never raw tenant ids, object keys, or URLs) so the Prometheus series count
  stays finite.

The M7 family complements the M4/M5 data_exchange metric names already emitted
(``data_exchange_export_requested_total``, ``data_exchange_export_deleted_total``,
``data_exchange_report_requested_total``, ``data_exchange_report_ready_total``,
``data_exchange_report_deleted_total``, ``data_exchange_report_downloaded_total``,
``data_exchange_report_request_http_total``).  The ops counters carry a
``_total`` suffix consistent with that set.
"""

from __future__ import annotations

from shared.logger.logger import metrics

#: Authoritative M7 ops metric-name list (documented + test-asserted).
METRIC_NAMES: tuple[str, ...] = (
    "data_exchange_ops_expired_total",              # live rows flipped to expired
    "data_exchange_ops_objects_deleted_total",      # ObjectStore bytes removed (expire)
    "data_exchange_ops_orphans_deleted_total",      # orphan object bytes removed (cleanup)
    "data_exchange_ops_reconcile_missing_total",    # rows whose object_key is absent (observed)
    "data_exchange_ops_reconcile_orphans_total",    # store objects with no row (observed)
    "data_exchange_ops_cleanup_refused_total",      # out-of-scope key / row refused
    "data_exchange_ops_egress_finalized_total",     # labels: disposition (bounded)
    "data_exchange_ops_legal_hold_blocked_total",   # expire blocked by an active hold
    "data_exchange_ops_sweep_errors_total",         # per-tenant sweep error
)

#: Bounded dispositions reported by the egress-finalization bridge (labels).
EGRESS_FINALIZED_DISPOSITIONS: tuple[str, ...] = (
    "available",            # completed straggler flipped to available (bytes durable)
    "failed",               # failed/cancelled job straggler flipped to failed
    "in_flight",            # job queued/running — left untouched
    "success_without_bytes",  # job succeeded but no bytes at the object key — left
    "no_job_record",        # no durable-job record to corroborate — left
)


def register_metrics() -> tuple[str, ...]:
    """Wire the M7 metric family.

    The shared ``MetricsCollector`` registers counters lazily on first use, so
    there is no allowlist to edit — this returns the authoritative names for
    callers/lifespan wiring and is a no-op that never raises.  Coordinator may
    call it from the FastAPI lifespan alongside the data_exchange job-handler
    registration.
    """
    return METRIC_NAMES


# ── expire sweep ────────────────────────────────────────────────────────────
def record_artifacts_expired(count: int = 1) -> None:
    if count > 0:
        metrics.increment("data_exchange_ops_expired_total", value=count)


def record_objects_deleted(count: int = 1) -> None:
    if count > 0:
        metrics.increment("data_exchange_ops_objects_deleted_total", value=count)


def record_orphan_objects_deleted(count: int = 1) -> None:
    if count > 0:
        metrics.increment("data_exchange_ops_orphans_deleted_total", value=count)


def record_legal_hold_blocked() -> None:
    metrics.increment("data_exchange_ops_legal_hold_blocked_total")


def record_sweep_error() -> None:
    metrics.increment("data_exchange_ops_sweep_errors_total")


# ── reconcile observations ──────────────────────────────────────────────────
def record_reconcile_missing(count: int = 1) -> None:
    if count > 0:
        metrics.increment("data_exchange_ops_reconcile_missing_total", value=count)


def record_reconcile_orphans(count: int = 1) -> None:
    if count > 0:
        metrics.increment("data_exchange_ops_reconcile_orphans_total", value=count)


# ── cleanup ─────────────────────────────────────────────────────────────────
def record_cleanup_refused() -> None:
    metrics.increment("data_exchange_ops_cleanup_refused_total")


# ── egress finalization ─────────────────────────────────────────────────────
def record_egress_finalized(disposition: str, count: int = 1) -> None:
    if count <= 0:
        return
    if disposition not in EGRESS_FINALIZED_DISPOSITIONS:  # bounded cardinality guard
        disposition = "no_job_record"
    metrics.increment(
        "data_exchange_ops_egress_finalized_total",
        value=count,
        labels={"disposition": disposition},
    )


# ── dashboard contribution ──────────────────────────────────────────────────
def ops_metrics_summary() -> dict:
    """Counter snapshot for just the M7 ops metric family.

    Contributes to the platform metrics dashboard by exposing the current
    counter values (labelled keys included) for the names in ``METRIC_NAMES``.
    """
    snapshot = metrics.snapshot()
    counters = snapshot.get("counters", {})
    selected: dict[str, int] = {}
    for key, value in counters.items():
        base = key.split("{", 1)[0]
        if base in METRIC_NAMES:
            selected[key] = value
    return {"data_exchange_ops": selected}


__all__ = [
    "METRIC_NAMES",
    "EGRESS_FINALIZED_DISPOSITIONS",
    "register_metrics",
    "record_artifacts_expired",
    "record_objects_deleted",
    "record_orphan_objects_deleted",
    "record_legal_hold_blocked",
    "record_sweep_error",
    "record_reconcile_missing",
    "record_reconcile_orphans",
    "record_cleanup_refused",
    "record_egress_finalized",
    "ops_metrics_summary",
]
