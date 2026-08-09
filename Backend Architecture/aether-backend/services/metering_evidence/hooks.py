"""Capability metering + entitlement enforcement hook (§7).

Single seam that commercial capability-execution paths call when a
dimension of usage occurs (ingestion, graph, Profile360, recommendations,
decisions, actions, outcomes, playbooks, audit exports, …). The hook
performs all three duties so the usage invariant holds at the point of
execution:

    tenant entitled, capability executed, usage occurred exactly once,
    evidence durable.

1. **Entitlement enforcement (fail-closed)** — consults
   ``EntitlementService.enforce_dimension``. A disabled / absent entitlement
   or usage beyond ``included_quantity`` with overage disallowed produces an
   explicit ``ENTITLEMENT_DENIED`` outcome (or raises
   :class:`EntitlementDeniedError` when ``raise_on_denied``), never a silent
   pass.

2. **Durable evidence** — writes a ``metering_evidence`` record via
   :class:`MeteringEvidenceService`. Dedupe is per-tenant fail-closed for
   double billing: a repeated ``dedupe_key`` is stored non-billable with
   ``excluded_reason="duplicate"``, which the hook reports as ``DUPLICATE``.

3. **Usage metering event** — writes the RevOps ``usage_metering_events``
   record via :class:`MeteringService` (idempotent on
   ``source_type``+``source_id``+``event_type``), keeping the metering-event
   truth in lockstep with the evidence truth so reconciliation can prove
   exactly-once usage.

Metering-store failure is NEVER silent: the hook raises
:class:`MeteringStoreError` by default (``raise_on_metering_error=True``)
or returns an explicit ``METERING_ERROR`` outcome. Billable loss must be
surfaced, not swallowed (see §5 of the metering reconciliation program).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from shared.common.common import AetherError, ErrorCode
from shared.logger.logger import get_logger

from services.billing.revops import (
    EntitlementDeniedError,
    EntitlementService,
    MeteringEventType,
    MeteringService,
    UsageMeteringEvent,
)

from .service import EXCLUDED_DUPLICATE, MeteringEvidenceService

logger = get_logger("aether.metering_evidence.hooks")

# ── Meter outcome states (stable API contract) ──────────────────────────────
METERED = "metered"
DUPLICATE = "duplicate"
ENTITLEMENT_DENIED = "entitlement_denied"
METERING_ERROR = "metering_error"

METERING_STATES: frozenset[str] = frozenset({
    METERED, DUPLICATE, ENTITLEMENT_DENIED, METERING_ERROR,
})


class MeteringStoreError(AetherError):
    """A metering store write failed — surfaced, never silently swallowed.

    Raised by the hook when ``raise_on_metering_error=True`` (the default)
    so a billable capability execution cannot be lost without an explicit
    signal to the caller.
    """

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(ErrorCode.SERVICE_UNAVAILABLE, message, **kwargs)


@dataclass
class MeterOutcome:
    """Result of a capability metering call.

    ``state`` is one of :data:`METERING_STATES`. ``metered_event_id`` is the
    ``usage_metering_events`` id, ``evidence_id`` the ``metering_evidence``
    id — both are durable writes that reconciliation can audit.
    """

    state: str
    dimension: str
    quantity: float
    metered_event_id: Optional[str] = None
    evidence_id: Optional[str] = None
    entitlement: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def meter_capability_usage(
    tenant_id: str,
    *,
    dimension: str,
    event_id: str,
    dedupe_key: str,
    source_path: str,
    quantity: float = 1,
    source_provider: str = "capability",
    package_id: str | None = None,
    billable: bool = True,
    enforce: bool = True,
    raise_on_denied: bool = True,
    raise_on_metering_error: bool = True,
    entitlements: EntitlementService | None = None,
    metering: MeteringService | None = None,
    evidence: MeteringEvidenceService | None = None,
    metadata: dict[str, Any] | None = None,
) -> MeterOutcome:
    """Enforce entitlement and meter one dimension of capability usage.

    Returns a :class:`MeterOutcome`. Raises :class:`EntitlementDeniedError`
    when ``enforce`` is set and the tenant is denied and ``raise_on_denied``
    is true; raises :class:`MeteringStoreError` when a metering write fails
    and ``raise_on_metering_error`` is true. Either outcome is explicit —
    nothing is silently dropped.
    """
    ent_svc = entitlements or EntitlementService()
    meter_svc = metering or MeteringService()
    evidence_svc = evidence or MeteringEvidenceService()
    quantity = float(quantity or 1)

    # ── 0. Dimension validity (fail-closed before any write) ──────────────
    # A non-canonical dimension would mint a phantom meter dimension that
    # entitlements can never cover and reconciliation can never audit.
    if dimension not in MeteringEventType.__args__:
        msg = f"unknown_usage_dimension: {dimension!r}"
        logger.error(msg)
        if raise_on_metering_error:
            raise MeteringStoreError(msg)
        return MeterOutcome(
            state=METERING_ERROR, dimension=dimension, quantity=quantity,
            reason="unknown_usage_dimension",
        )

    # ── 1. Entitlement enforcement (fail-closed) ──────────────────────────
    decision: dict[str, Any] | None = None
    if enforce:
        decision = await ent_svc.enforce_dimension(tenant_id, dimension, quantity, package_id)
        if decision['state'] == 'denied':
            if raise_on_denied:
                raise EntitlementDeniedError(dimension, decision['reason'])
            return MeterOutcome(
                state=ENTITLEMENT_DENIED,
                dimension=dimension,
                quantity=quantity,
                entitlement=decision,
                reason=decision['reason'],
            )

    # ── 2. Durable evidence (dedupe fail-closed for double billing) ───────
    try:
        evidence_record = await evidence_svc.record(
            tenant_id=tenant_id,
            source_path=source_path,
            event_id=event_id,
            dedupe_key=dedupe_key,
            source_provider=source_provider,
            usage_dimension=dimension,
            quantity=quantity,
            billable=billable,
            metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover - surfaced, never silent
        msg = f"metering_evidence_write_failed dimension={dimension}: {exc}"
        logger.error(msg)
        if raise_on_metering_error:
            raise MeteringStoreError(msg) from exc
        return MeterOutcome(
            state=METERING_ERROR, dimension=dimension, quantity=quantity,
            reason="evidence_write_failed", metadata={"error": str(exc)},
        )

    # ── 3. Usage metering event (RevOps truth, idempotent) ────────────────
    event = UsageMeteringEvent(
        tenant_id=tenant_id,
        event_type=dimension,
        quantity=quantity,
        source_id=event_id,
        source_type=source_provider,
        billable=billable,
        package_id=package_id,
        metadata=metadata,
    )
    try:
        meter_record = await meter_svc.record_event(event)
    except Exception as exc:  # pragma: no cover - surfaced, never silent
        msg = f"usage_metering_event_write_failed dimension={dimension}: {exc}"
        logger.error(msg)
        if raise_on_metering_error:
            raise MeteringStoreError(msg) from exc
        return MeterOutcome(
            state=METERING_ERROR, dimension=dimension, quantity=quantity,
            evidence_id=evidence_record.get('metered_event_id'),
            reason="usage_event_write_failed", metadata={"error": str(exc)},
        )

    state = (
        DUPLICATE
        if evidence_record.get('excluded_reason') == EXCLUDED_DUPLICATE
        else METERED
    )
    return MeterOutcome(
        state=state,
        dimension=dimension,
        quantity=quantity,
        metered_event_id=(meter_record or {}).get('metering_event_id'),
        evidence_id=evidence_record.get('metered_event_id'),
        entitlement=decision,
        reason=evidence_record.get('billing_reason') if state == DUPLICATE else None,
        metadata=metadata or {},
    )


__all__ = [
    "DUPLICATE",
    "ENTITLEMENT_DENIED",
    "METERED",
    "METERING_ERROR",
    "METERING_STATES",
    "MeteringStoreError",
    "MeterOutcome",
    "meter_capability_usage",
]
