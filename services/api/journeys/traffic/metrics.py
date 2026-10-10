"""Traffic-intelligence observability metric set (spec §16).

A single, named surface for every counter/latency the traffic path emits so
metric names stay stable and are discoverable from one module. Everything
delegates to the shared collector (``shared.logger.logger.metrics``) and
``shared.observability.emit_latency``; there is no independent state here.

Label cardinality is intentionally bounded to canonical registry vocabulary
(source_class, proof_level, entry-method state, correlation status) — never raw
tenant ids or URLs — so the Prometheus series count stays finite.

Import and call these helpers rather than sprinkling ``metrics.increment`` with
ad-hoc names across the codebase. ``METRIC_NAMES`` is the authoritative list and
is asserted against in tests and rendered in
docs/observability/traffic-intelligence-metrics.md.
"""

from __future__ import annotations

from shared.logger.logger import metrics
from shared.observability import emit_latency

# Authoritative metric name registry (documented + test-asserted).
METRIC_NAMES: tuple[str, ...] = (
    "classification_total",
    "direct_unknown_total",
    "evidence_conflict_total",
    "invalid_source_link_total",
    "source_link_replay_total",
    "handoff_correlation_total",
    "redirect_latency_ms",
    "navigation_correlation_total",
    "install_referrer_retrieval_total",
    "app_link_processing_total",
    "universal_link_processing_total",
    "deferred_attribution_total",
    "adattributionkit_ingestion_total",
    "sdk_deep_link_parse_failure_total",
    "reclassification_throughput_total",
    "reclassification_failure_total",
    "machine_excluded_total",
    "shadow_divergence_total",
)


# ── Classification path ─────────────────────────────────────────────────────
def record_classification(source_class: str, proof_level: str) -> None:
    """One counted classification, split by source_class and proof_level."""
    metrics.increment("classification_total", labels={"source_class": source_class})
    metrics.increment("classification_total", labels={"proof_level": proof_level})


def record_direct_unknown() -> None:
    metrics.increment("direct_unknown_total")


def record_evidence_conflict(count: int = 1) -> None:
    if count > 0:
        metrics.increment("evidence_conflict_total", value=count)


def record_machine_excluded() -> None:
    metrics.increment("machine_excluded_total")


# ── Verified source-link / redirect path ────────────────────────────────────
def record_invalid_source_link() -> None:
    metrics.increment("invalid_source_link_total")


def record_source_link_replay() -> None:
    metrics.increment("source_link_replay_total")


def record_handoff_correlation(status: str) -> None:
    """status ∈ {success, expired, failed} (bounded)."""
    metrics.increment("handoff_correlation_total", labels={"status": status})


def record_redirect_latency(ms: float) -> None:
    emit_latency("redirect", ms)


# ── Web navigation correlation ──────────────────────────────────────────────
def record_navigation_correlation(status: str) -> None:
    metrics.increment("navigation_correlation_total", labels={"status": status})


# ── Native entry methods ────────────────────────────────────────────────────
def record_install_referrer_retrieval(state: str) -> None:
    """state ∈ {retrieved, empty, unavailable, error} (bounded)."""
    metrics.increment("install_referrer_retrieval_total", labels={"state": state})


def record_app_link_processing() -> None:
    metrics.increment("app_link_processing_total")


def record_universal_link_processing() -> None:
    metrics.increment("universal_link_processing_total")


def record_deferred_attribution(status: str) -> None:
    """status ∈ {resolved, unmatched, expired} (bounded)."""
    metrics.increment("deferred_attribution_total", labels={"status": status})


def record_adattributionkit_ingestion() -> None:
    """Emitted from the AdAttributionKit ingestion hook (other agents call this)."""
    metrics.increment("adattributionkit_ingestion_total")


def record_sdk_deep_link_parse_failure() -> None:
    metrics.increment("sdk_deep_link_parse_failure_total")


# ── Historical reclassification (repair) ────────────────────────────────────
def record_reclassification_throughput(count: int = 1) -> None:
    if count > 0:
        metrics.increment("reclassification_throughput_total", value=count)


def record_reclassification_failure(count: int = 1) -> None:
    if count > 0:
        metrics.increment("reclassification_failure_total", value=count)


# ── Shadow classification divergence ────────────────────────────────────────
def record_shadow_divergence(diverged: bool) -> None:
    metrics.increment(
        "shadow_divergence_total", labels={"diverged": "true" if diverged else "false"}
    )


# ── Dashboard contribution ──────────────────────────────────────────────────
def traffic_metrics_summary() -> dict:
    """Counter snapshot for just the traffic-intelligence metric family.

    Contributes to the platform metrics dashboard by exposing the current
    counter values (labelled keys included) for the names in ``METRIC_NAMES``.
    """
    snapshot = metrics.snapshot()
    counters = snapshot.get("counters", {})
    selected: dict[str, int] = {}
    for key, value in counters.items():
        # Collector key format is ``name{label=value,...}`` (see MetricsCollector._key).
        base = key.split("{", 1)[0]
        if base in METRIC_NAMES:
            selected[key] = value
    return {"traffic_intelligence": selected}


__all__ = [
    "METRIC_NAMES",
    "record_classification",
    "record_direct_unknown",
    "record_evidence_conflict",
    "record_machine_excluded",
    "record_invalid_source_link",
    "record_source_link_replay",
    "record_handoff_correlation",
    "record_redirect_latency",
    "record_navigation_correlation",
    "record_install_referrer_retrieval",
    "record_app_link_processing",
    "record_universal_link_processing",
    "record_deferred_attribution",
    "record_adattributionkit_ingestion",
    "record_sdk_deep_link_parse_failure",
    "record_reclassification_throughput",
    "record_reclassification_failure",
    "record_shadow_divergence",
    "traffic_metrics_summary",
]
