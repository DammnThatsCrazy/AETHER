"""
Aether Service — Ingestion Funnel Observability + Observation Inspector ledger
(WS-E 1/2/3, blueprint §17).

Default-OFF instrumentation around the canonical ingestion spine
(``services/ingestion/batch.py``) and the Bronze → Silver → projection workers
(``services/ingestion/workers.py``). When ``settings.ingestion_observability.enabled``
is true it records two complementary views:

* the **funnel** — per-stage aggregate counters (observations received, and the
  per-stage disposition counts accepted / duplicate / rejected / degraded), and
* **per-observation traces** keyed by ``{tenant_id}:{event_id}`` that the Kyber
  Observation Inspector renders as the blueprint §17 ladder (RAW → RECEIVED →
  VALIDATED → BRONZE → NORMALIZED → RESOLVED → RELATIONSHIPS → GRAPH MUTATIONS →
  PROJECTIONS → METRICS / FINDINGS).

Honest scope (this slice):

* RAW is client-side and never observed here.
* RECEIVED / VALIDATED / BRONZE are recorded by the API process that runs
  ``ingest_events``; NORMALIZED and PROJECTIONS are recorded by the ingestion
  worker functions (``silver_normalizer`` / ``silver_fact_projector``).
* RESOLVED / RELATIONSHIPS / GRAPH MUTATIONS / METRICS-FINDINGS happen downstream
  of this slice — they are declared in the stage vocabulary so the control plane
  renders the full ladder, but are not yet instrumented (each stage's payload
  reports ``monitored: false``).
* The ledger is **in-process** (it mirrors the existing in-process
  ``MetricsCollector`` conventions in shared/logger/logger.py). In a
  multi-process deployment each process aggregates what it observes; the
  operator surfaces it feeds reflect that process. Durable, cross-worker tracing
  is a documented follow-on, not this slice.

Recording is a pure side channel: it NEVER changes event dispositions, never
rejects, and no-ops (a single boolean check) while the flag is OFF.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import settings
from shared.logger.logger import metrics

# ── Blueprint §17 Observation Inspector stage vocabulary ──────────────────────
# Order is the display ladder. ``raw`` is client-side (declared for the ladder;
# not monitored server-side). ``resolved`` onward are downstream of this slice.
FUNNEL_STAGES: tuple[str, ...] = (
    "raw",
    "received",
    "validated",
    "bronze",
    "normalized",
    "resolved",
    "relationships",
    "graph_mutations",
    "projections",
    "metrics_findings",
)

_MONITORED_STAGES: frozenset[str] = frozenset({
    "received",
    "validated",
    "bronze",
    "normalized",
    "projections",
})

_STAGE_DISPLAY: dict[str, str] = {
    "raw": "RAW",
    "received": "RECEIVED",
    "validated": "VALIDATED",
    "bronze": "BRONZE",
    "normalized": "NORMALIZED",
    "resolved": "RESOLVED",
    "relationships": "RELATIONSHIPS",
    "graph_mutations": "GRAPH MUTATIONS",
    "projections": "PROJECTIONS",
    "metrics_findings": "METRICS / FINDINGS",
}

# Ingestion dispositions that can land on a stage bucket (mirrors the accepted /
# duplicate / rejected status vocabulary plus degraded for flag fail-open paths).
_VALID_DISPOSITIONS: frozenset[str] = frozenset({
    "accepted",
    "duplicate",
    "rejected",
    "degraded",
    "observed",
})

_MAX_TRACES = 2_000


def observability_enabled() -> bool:
    """True when the ingestion-observability instrumentation should record."""
    return settings.ingestion_observability.enabled


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ── Funnel ledger ─────────────────────────────────────────────────────────────

class IngestionFunnel:
    """Per-stage aggregate funnel counters (in-process, mirroring metrics)."""

    def __init__(self) -> None:
        self._stage_buckets: dict[str, dict[str, int]] = {
            stage: {} for stage in FUNNEL_STAGES
        }
        self._totals: dict[str, int] = {stage: 0 for stage in FUNNEL_STAGES}
        self._degraded: int = 0

    def record(self, stage: str, status: str = "observed") -> None:
        """Increment one stage bucket. Unknown stages/dispositions are ignored."""
        if stage not in self._totals:
            return
        status = status if status in _VALID_DISPOSITIONS else "observed"
        bucket = self._stage_buckets[stage]
        bucket[status] = bucket.get(status, 0) + 1
        self._totals[stage] += 1
        metrics.increment(f"ingestion_funnel_{stage}_total", labels={"status": status})

    def record_degraded(self) -> None:
        """Count a flag fail-open degrade (envelope/gateway rejected → flat path)."""
        self._degraded += 1

    def snapshot(self) -> dict[str, Any]:
        stages: list[dict[str, Any]] = []
        for stage in FUNNEL_STAGES:
            counts = self._stage_buckets[stage]
            stages.append({
                "stage": stage,
                "display": _STAGE_DISPLAY[stage],
                "monitored": stage in _MONITORED_STAGES,
                "total": self._totals[stage],
                "by_status": dict(counts),
            })
        validated = self._stage_buckets["validated"]
        return {
            "stages": stages,
            "rollup": {
                "received": self._totals["received"],
                "accepted": validated.get("accepted", 0),
                "duplicates": validated.get("duplicate", 0),
                "rejected": validated.get("rejected", 0),
                "degraded": self._degraded,
            },
        }


# ── Observation trace store (Observation Inspector) ──────────────────────────

class ObservationTrace:
    """One observation's journey across the monitored stages."""

    def __init__(
        self,
        tenant_id: str,
        event_id: str,
        event_type: str = "",
        path: str = "sdk",
    ) -> None:
        self.tenant_id = tenant_id
        self.event_id = event_id
        self.event_type = event_type
        self.path = path
        self.started_at = _iso_now()
        self.spans: list[dict[str, Any]] = []
        self.outcome: Optional[str] = None

    def add_span(
        self,
        stage: str,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        self.spans.append({
            "stage": stage,
            "display": _STAGE_DISPLAY.get(stage, stage.upper()),
            "status": status,
            "at_ms": _ms_now(),
            "detail": detail,
        })
        self.outcome = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "path": self.path,
            "started_at": self.started_at,
            "outcome": self.outcome,
            "spans": self.spans,
            "complete": self.outcome in ("accepted", "rejected"),
        }


class TraceStore:
    """Bounded in-memory store of observation traces (key = tenant:event)."""

    def __init__(self, capacity: int = _MAX_TRACES) -> None:
        self._capacity = capacity
        self._traces: "OrderedDict[str, ObservationTrace]" = OrderedDict()

    def start(self, key: str, trace: ObservationTrace) -> ObservationTrace:
        if key not in self._traces:
            self._traces[key] = trace
            self._evict()
        return self._traces[key]

    def get(self, key: str) -> Optional[ObservationTrace]:
        trace = self._traces.get(key)
        if trace is not None:
            self._traces.move_to_end(key)
        return trace

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        items = list(self._traces.values())
        return [t.to_dict() for t in items[-limit:]]

    def __len__(self) -> int:
        return len(self._traces)

    def _evict(self) -> None:
        while len(self._traces) > self._capacity:
            self._traces.popitem(last=False)


# ── Module singletons + public recording seam ─────────────────────────────────

_funnel = IngestionFunnel()
_traces = TraceStore()


def _event_key(tenant_id: str, event_id: str) -> str:
    return f"{tenant_id}:{event_id}"


def record_stage(
    *,
    tenant_id: str = "",
    event_id: Optional[str] = None,
    event_type: str = "",
    stage: str,
    status: str = "observed",
    path: str = "sdk",
    detail: Optional[str] = None,
) -> None:
    """Record one stage observation (funnel bucket + trace span when present).

    No-op while the ingestion-observability flag is OFF. ``stage`` must be a
    member of FUNNEL_STAGES; unknown stages are ignored.
    """
    if not observability_enabled():
        return
    if stage not in FUNNEL_STAGES:
        return
    _funnel.record(stage, status)
    if event_id:
        key = _event_key(tenant_id, event_id)
        trace = _traces.get(key)
        if trace is None:
            trace = _traces.start(
                key, ObservationTrace(tenant_id, event_id, event_type, path)
            )
        trace.add_span(stage, status, detail)


def record_degraded(tenant_id: str = "", event_id: Optional[str] = None) -> None:
    """Count a flag fail-open degrade on the funnel (never a disposition)."""
    if not observability_enabled():
        return
    _funnel.record_degraded()
    if event_id:
        record_stage(
            tenant_id=tenant_id,
            event_id=event_id,
            stage="bronze",
            status="degraded",
            detail="envelope_or_gateway_degraded_to_flat_sdk_path",
        )


# ── Operator-facing snapshots ─────────────────────────────────────────────────

def funnel_snapshot() -> dict[str, Any]:
    """Funnel telemetry for the Kyber ingestion control plane."""
    snapshot = _funnel.snapshot()
    return {
        "enabled": observability_enabled(),
        "recorded_at": _iso_now(),
        "instrumentation": {
            "monitored_stages": sorted(_MONITORED_STAGES),
            "declared_unmonitored": sorted(
                set(FUNNEL_STAGES) - _MONITORED_STAGES
            ),
            "scope": (
                "in-process ledger; multi-process deployments aggregate per "
                "process (durable cross-worker tracing is a documented follow-on)"
            ),
        },
        "rollup": snapshot["rollup"],
        "stages": snapshot["stages"],
    }


def trace_snapshot(tenant_id: str, event_id: str) -> Optional[dict[str, Any]]:
    """One observation's inspector trace, or None when unknown/flag-off."""
    if not observability_enabled():
        return None
    trace = _traces.get(_event_key(tenant_id, event_id))
    return trace.to_dict() if trace is not None else None


def recent_trace_snapshot(limit: int = 50) -> list[dict[str, Any]]:
    if not observability_enabled():
        return []
    return _traces.recent(limit=min(max(limit, 1), 200))


def pipeline_snapshot() -> dict[str, Any]:
    """GET /v1/health/pipeline payload — ingestion funnel health summary.

    Mirrors the gateway health conventions: always returns 200-shaped data; a
    disabled pipeline reports ``enabled: false`` with zeroed counters rather
    than erroring, so the liveness surface stays stable while the flag is OFF.
    """
    snapshot = _funnel.snapshot()
    rollup = snapshot["rollup"]
    overall = "disabled"
    if observability_enabled():
        if rollup["rejected"] or rollup["degraded"]:
            overall = "degraded"
        else:
            overall = "healthy"
    return {
        "probe": "ingestion-pipeline",
        "status": overall,
        "enabled": observability_enabled(),
        "timestamp": _iso_now(),
        "pipeline": {
            "received": rollup["received"],
            "accepted": rollup["accepted"],
            "duplicates": rollup["duplicates"],
            "rejected": rollup["rejected"],
            "degraded": rollup["degraded"],
        },
        "stages": snapshot["stages"],
    }
