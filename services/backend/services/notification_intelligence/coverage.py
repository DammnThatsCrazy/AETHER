"""Producer-coverage registry for the notification/attention plane.

A *producer* is a source that emits intelligence notifications (`POST /v1/notifications/
intelligence`, keyed by ``source_service``). Coverage answers, honestly: *is each
producer we expect to be emitting actually emitting within its freshness window?* — so
a silent producer (a broken feed) is visible instead of read as "all quiet, all well".

Honesty contract (mirrors the rest of this program — declare the framework, never
fabricate the policy):

  * The registry declares the **known** producers. It does NOT fabricate service-level
    objectives: producers ship ``required=False`` with a conservative default freshness
    window. Declaring a producer ``required=True`` with a real cadence is an operator
    decision (this is the coverage *baseline*).
  * Overall coverage is **never** ``healthy`` unless a baseline is declared AND every
    required producer is healthy. With no required producer declared, the honest overall
    state is ``coverage_incomplete`` (we have no basis to assert health), never
    ``healthy``.
  * A producer we have never observed is ``unknown`` (or ``unavailable`` if required) —
    never silently treated as healthy.

The backing signal is an **in-process heartbeat** stamped when a notification is emitted
(so it reflects the serving process's observations since start; a durable cross-process
store is a later increment). It never fabricates a timestamp for an unobserved producer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from shared.temporal.instant import ensure_aware_utc, to_iso_utc, try_parse_instant
from shared.common.common import utc_now


class CoverageState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    COVERAGE_INCOMPLETE = "coverage_incomplete"
    DISABLED_INTENTIONALLY = "disabled_intentionally"
    EXTERNALLY_BLOCKED = "externally_blocked"


# States that count as "resolved OK" for the required-coverage roll-up. A producer
# intentionally disabled or externally blocked is a *lawful* non-emission — it does not
# by itself make coverage incomplete, but it is surfaced.
_OK_STATES = frozenset({CoverageState.HEALTHY, CoverageState.DISABLED_INTENTIONALLY,
                        CoverageState.EXTERNALLY_BLOCKED})
# Attention states, worst-first, for the overall roll-up.
_ATTENTION_ORDER = (
    CoverageState.UNAVAILABLE,
    CoverageState.UNKNOWN,
    CoverageState.STALE,
    CoverageState.DEGRADED,
)


@dataclass(frozen=True)
class ProducerSpec:
    id: str
    description: str
    required: bool = False
    max_staleness_seconds: int = 3600
    #: A static, non-liveness state: an intentionally-disabled or credential-blocked
    #: producer that should not be evaluated against its freshness window.
    static_state: Optional[CoverageState] = None


# Known producers of the notification plane (real ``source_service`` values seen in the
# codebase). Declared required=False: this is the framework, not a fabricated SLA. Flip
# required=True + tune max_staleness_seconds to enforce a coverage baseline.
PRODUCER_REGISTRY: tuple[ProducerSpec, ...] = (
    ProducerSpec("identity", "Identity graph reconciliation alerts"),
    ProducerSpec("jobs", "Durable jobs / worker supervisor alerts"),
    ProducerSpec("agents", "User-agent operational notifications"),
    ProducerSpec("sdk_drift", "SDK drift detection"),
    ProducerSpec("sdk_config", "SDK config change notifications"),
    ProducerSpec("onchain", "On-chain action recorder"),
    ProducerSpec("delivery_worker", "Delivery worker agent-assist"),
    ProducerSpec("x402", "x402 settlement / verification / approvals plane"),
)


@dataclass
class ProducerCoverage:
    producer_id: str
    state: CoverageState
    required: bool
    last_emit_at: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "producer_id": self.producer_id,
            "state": self.state.value,
            "required": self.required,
            "last_emit_at": self.last_emit_at,
            "detail": self.detail,
        }


@dataclass
class CoverageReport:
    overall_state: CoverageState
    generated_at: str
    producers: list[ProducerCoverage] = field(default_factory=list)
    #: Producers observed emitting that are NOT in the registry (informational).
    unregistered_observed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall_state": self.overall_state.value,
            "generated_at": self.generated_at,
            "producers": [p.to_dict() for p in self.producers],
            "unregistered_observed": sorted(self.unregistered_observed),
        }


def _evaluate_one(spec: ProducerSpec, last_emit: Optional[datetime], now: datetime) -> ProducerCoverage:
    if spec.static_state is not None:
        return ProducerCoverage(spec.id, spec.static_state, spec.required,
                                detail=f"static: {spec.static_state.value}")
    if last_emit is None:
        state = CoverageState.UNAVAILABLE if spec.required else CoverageState.UNKNOWN
        return ProducerCoverage(spec.id, state, spec.required, detail="no emission observed")
    age = (now - last_emit).total_seconds()
    if age <= spec.max_staleness_seconds:
        state = CoverageState.HEALTHY
    elif age <= 2 * spec.max_staleness_seconds:
        state = CoverageState.DEGRADED
    else:
        state = CoverageState.STALE
    return ProducerCoverage(spec.id, state, spec.required, last_emit_at=to_iso_utc(last_emit),
                            detail=f"last emit {int(age)}s ago")


def evaluate_coverage(
    specs: tuple[ProducerSpec, ...],
    last_emit_by_producer: dict[str, Optional[str]],
    now: Optional[datetime] = None,
) -> CoverageReport:
    """Pure evaluation: registry + observed last-emit map → an honest coverage report."""
    now = ensure_aware_utc(now) if now is not None else utc_now()
    coverages: list[ProducerCoverage] = []
    for spec in specs:
        raw = last_emit_by_producer.get(spec.id)
        parsed, _err = try_parse_instant(raw) if raw else (None, None)
        coverages.append(_evaluate_one(spec, parsed, now))

    registered = {s.id for s in specs}
    unregistered = [pid for pid in last_emit_by_producer if pid not in registered]

    required = [c for c in coverages if c.required]
    if not required:
        # No baseline declared → we cannot assert health. Honest, not "healthy".
        overall = CoverageState.COVERAGE_INCOMPLETE
    else:
        overall = CoverageState.HEALTHY
        for attention in _ATTENTION_ORDER:
            if any(c.state == attention for c in required):
                overall = (CoverageState.COVERAGE_INCOMPLETE
                           if attention in (CoverageState.UNAVAILABLE, CoverageState.UNKNOWN)
                           else attention)
                break
    return CoverageReport(overall, to_iso_utc(now), coverages, unregistered)


# ── in-process heartbeat ─────────────────────────────────────────────────────
# Reflects THIS process's observed emissions since start. Never a fabricated stamp.

_HEARTBEATS: dict[str, str] = {}


def record_producer_emit(producer_id: Optional[str]) -> None:
    """Stamp a producer's last-emit at 'now'. No-op for an empty producer id."""
    if not producer_id:
        return
    _HEARTBEATS[str(producer_id)] = to_iso_utc(utc_now())


def heartbeat_snapshot() -> dict[str, Optional[str]]:
    return dict(_HEARTBEATS)


def reset_heartbeats() -> None:
    """Test hook."""
    _HEARTBEATS.clear()


def build_coverage_report() -> CoverageReport:
    return evaluate_coverage(PRODUCER_REGISTRY, heartbeat_snapshot())
