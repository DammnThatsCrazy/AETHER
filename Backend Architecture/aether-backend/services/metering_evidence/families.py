"""Commercial capability-family registry for metering (§7) + re-homed seam.

Maps each commercial capability family to its canonical usage dimension and
default source path so capability-execution paths can meter with a one-line
call and never invent ad-hoc dimension strings. The integration pass wraps
each family's execution path with the matching ``meter_*_family`` helper
(see ``wiringNeeds`` in the program ledger); the registry here is the single
source of truth for the mapping so meter + reconciliation stay dimension-
aligned.

This module also hosts the **re-homed capability metering + entitlement
enforcement seam**. The credential-turnkey branch shipped that seam in
``services/metering_evidence/hooks.py`` and ``services/capabilities/
enforcement.py``; neither module exists on main (main's canonical substrate is
``services/billing/revops.py`` for entitlement/metering and
``services/metering_evidence/service.py`` for durable evidence). To avoid
re-porting superseded modules, the seam lives here and is implemented on top
of main's canonical classes (``EntitlementService``, ``MeteringService``,
``MeteringEvidenceService``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from shared.common.common import AetherError, ErrorCode
from shared.logger.logger import get_logger

from services.billing.revops import (
    EntitlementService,
    MeteringEventType,
    MeteringService,
    UsageMeteringEvent,
)
from services.metering_evidence.service import (
    EXCLUDED_DUPLICATE,
    MeteringEvidenceService,
)

logger = get_logger("aether.metering_evidence.families")

# Canonical MeteringEventType values — guarantees every family maps onto a
# valid literal (fail-closed at the hook, before any write).
_VALID = frozenset(MeteringEventType.__args__)


# ── Re-homed capability metering + entitlement enforcement seam ─────────────

# Meter outcome states (stable API contract).
METERED = "metered"
DUPLICATE = "duplicate"
ENTITLEMENT_DENIED = "entitlement_denied"
METERING_ERROR = "metering_error"

METERING_STATES: frozenset[str] = frozenset({
    METERED, DUPLICATE, ENTITLEMENT_DENIED, METERING_ERROR,
})

# Canonical fail-closed entitlement decision states. ``included`` and
# ``overage`` are allowed; ``denied`` is enforced (never silently passed).
ENTITLEMENT_STATE_INCLUDED = "included"
ENTITLEMENT_STATE_OVERAGE = "overage"
ENTITLEMENT_STATE_DENIED = "denied"

# Machine-readable denial reasons (stable API contract).
ENTITLEMENT_DENY_NOT_ENTITLED = "not_entitled"
ENTITLEMENT_DENY_DISABLED = "disabled"
ENTITLEMENT_DENY_OVERAGE_NOT_ALLOWED = "overage_not_allowed"


class MeteringStoreError(AetherError):
    """A metering store write failed — surfaced, never silently swallowed.

    Raised by the hook when ``raise_on_metering_error=True`` (the default)
    so a billable capability execution cannot be lost without an explicit
    signal to the caller.
    """

    def __init__(self, message: str, **kwargs: Any):
        super().__init__(ErrorCode.SERVICE_UNAVAILABLE, message, **kwargs)


class EntitlementDeniedError(AetherError):
    """Fail-closed dimension-level entitlement denial (HTTP 403).

    Raised by capability-execution paths (and the enforcement seam) when a
    tenant is not entitled to use a dimension: feature disabled, no
    entitlement record, or usage beyond ``included_quantity`` with overage
    not allowed. Never silent — the caller must surface this to the tenant.
    """

    def __init__(self, dimension: str, reason: str = "not_entitled", **kwargs: Any):
        super().__init__(
            ErrorCode.FORBIDDEN,
            f"Entitlement denied for dimension '{dimension}' ({reason})",
            details={"dimension": dimension, "reason": reason},
            **kwargs,
        )


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


@dataclass
class EnforcementResult:
    """Outcome of an entitlement enforcement call.

    ``allowed`` is False only when ``state == "denied"``. ``reason`` is the
    machine-readable denial reason (``not_entitled`` | ``disabled`` |
    ``overage_not_allowed``) or the allowed state.
    """

    allowed: bool
    state: str
    reason: str
    dimension: str
    quantity: float
    included_quantity: float
    overage_quantity: float
    entitlement: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityEntitlementService(EntitlementService):
    """Main's ``services.billing.revops.EntitlementService`` + dimension-level
    fail-closed enforcement.

    Re-home of the branch's ``EntitlementService.enforce_dimension`` seam: the
    branch added the method to ``revops.py``, but main's canonical revops does
    not carry it, so it lives here on top of main's repository surface
    (``TenantEntitlementRepository.list_for_tenant``).
    """

    async def enforce_dimension(
        self,
        tenant_id: str,
        dimension: str,
        quantity: float,
        package_id: str | None = None,
    ) -> dict[str, Any]:
        """Fail-closed dimension-level entitlement decision.

        Deterministic (never raises): returns a decision dict with ``state``
        ``included`` | ``overage`` | ``denied`` plus the machine-readable
        ``reason``. Dimension-level semantics:

        * no entitlement record for ``dimension``            -> denied (not_entitled)
        * entitlement present but ``enabled`` is false       -> denied (disabled)
        * ``quantity`` within ``included_quantity``          -> included
        * ``quantity`` beyond ``included_quantity`` when
          ``overage_allowed`` is true                        -> overage
        * ``quantity`` beyond ``included_quantity`` when
          overage is not allowed                             -> denied (overage_not_allowed)
        """
        ents = await self.entitlements.list_for_tenant(tenant_id)
        by_feature = {e['feature_key']: e for e in ents}
        ent = by_feature.get(dimension)
        quantity = float(quantity or 0)
        included = float(ent.get('included_quantity') or 0) if ent else 0.0
        overage_allowed = bool(ent and ent.get('overage_allowed', False))
        decision: dict[str, Any] = {
            'tenant_id': tenant_id,
            'dimension': dimension,
            'quantity': quantity,
            'entitlement': ent,
            'enabled': bool(ent and ent.get('enabled', True)),
            'included_quantity': included,
            'overage_allowed': overage_allowed,
            'overage_quantity': 0.0,
            'state': ENTITLEMENT_STATE_INCLUDED,
            'reason': ENTITLEMENT_STATE_INCLUDED,
        }
        if ent is None:
            decision['state'] = ENTITLEMENT_STATE_DENIED
            decision['reason'] = ENTITLEMENT_DENY_NOT_ENTITLED
            return decision
        if not ent.get('enabled', True):
            decision['state'] = ENTITLEMENT_STATE_DENIED
            decision['reason'] = ENTITLEMENT_DENY_DISABLED
            return decision
        if quantity > included and not overage_allowed:
            decision['state'] = ENTITLEMENT_STATE_DENIED
            decision['reason'] = ENTITLEMENT_DENY_OVERAGE_NOT_ALLOWED
            decision['overage_quantity'] = quantity - included
            return decision
        if quantity > included:
            decision['state'] = ENTITLEMENT_STATE_OVERAGE
            decision['reason'] = ENTITLEMENT_STATE_OVERAGE
            decision['overage_quantity'] = quantity - included
        return decision


async def enforce_entitlement(
    tenant_id: str,
    dimension: str,
    quantity: float,
    *,
    entitlements: CapabilityEntitlementService | None = None,
    package_id: str | None = None,
    fail_closed: bool = True,
) -> EnforcementResult:
    """Enforce dimension-level entitlement for a capability execution.

    Fail-closed by default: raises :class:`EntitlementDeniedError` when the
    tenant is not entitled. With ``fail_closed=False`` returns the decision
    (``allowed=False`` + ``reason``) without raising, for advisory callers.
    """
    svc = entitlements or CapabilityEntitlementService()
    decision = await svc.enforce_dimension(tenant_id, dimension, quantity, package_id)
    denied = decision['state'] == ENTITLEMENT_STATE_DENIED
    result = EnforcementResult(
        allowed=not denied,
        state=decision['state'],
        reason=decision['reason'],
        dimension=dimension,
        quantity=float(quantity or 0),
        included_quantity=decision['included_quantity'],
        overage_quantity=decision['overage_quantity'],
        entitlement=decision['entitlement'],
    )
    if denied and fail_closed:
        raise EntitlementDeniedError(dimension, decision['reason'])
    return result


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
    ent_svc = entitlements or CapabilityEntitlementService()
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
        if decision['state'] == ENTITLEMENT_STATE_DENIED:
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


# ── Capability-family registry ──────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityFamily:
    """Registry entry: a capability family -> canonical metering contract."""

    family: str
    dimension: str
    source_path: str
    source_provider: str = "capability"

    def __post_init__(self) -> None:
        if self.dimension not in _VALID:
            raise ValueError(
                f"family {self.family!r} maps to non-canonical dimension "
                f"{self.dimension!r}; must be one of MeteringEventType"
            )


CAPABILITY_FAMILIES: dict[str, CapabilityFamily] = {
    name: CapabilityFamily(family=name, dimension=dim, source_path=path)
    for name, dim, path in [
        ("ingestion", "event_ingested", "/v1/ingest/events"),
        ("graph", "graph_operation", "/v1/graph"),
        ("profile360", "profile_query", "/v1/profile/resolve"),
        ("recommendations", "recommendation_generated", "/v1/intelligence/recommendations"),
        ("decisions", "decision_recorded", "/v1/intelligence/decisions"),
        ("actions", "action_logged", "/v1/automation/actions"),
        ("outcomes", "outcome_observed", "/v1/delivery/outcomes"),
        ("playbooks", "playbook_run", "/v1/automation/playbooks"),
        ("audit_exports", "audit_export_generated", "/v1/audit/exports"),
        ("investigations", "investigation_opened", "/v1/intelligence/investigations"),
        ("connector_syncs", "connector_sync", "/v1/integrations/connectors/sync"),
        ("webhooks", "webhook_ingested", "/v1/integrations/webhooks/events"),
    ]
}


def is_known_family(family: str) -> bool:
    return family in CAPABILITY_FAMILIES


def family_dimension(family: str) -> str:
    """Return the canonical metering dimension for a family (KeyError if unknown)."""
    return CAPABILITY_FAMILIES[family].dimension


async def meter_family_usage(
    family: str,
    tenant_id: str,
    *,
    event_id: str,
    dedupe_key: str | None = None,
    quantity: float = 1,
    package_id: str | None = None,
    billable: bool = True,
    enforce: bool = True,
    raise_on_denied: bool = True,
    raise_on_metering_error: bool = True,
    entitlements: Any = None,
    metering: Any = None,
    evidence: Any = None,
    metadata: Optional[dict[str, Any]] = None,
) -> MeterOutcome:
    """Meter one capability-family usage unit via the shared hook.

    ``event_id`` is the caller's unique event id (used for idempotency on the
    usage-meting event); ``dedupe_key`` defaults to ``f"{family}:{event_id}"``
    so replays are recorded once and never double-billed.
    """
    if family not in CAPABILITY_FAMILIES:
        raise KeyError(f"Unknown capability family: {family!r}")
    spec = CAPABILITY_FAMILIES[family]
    return await meter_capability_usage(
        tenant_id,
        dimension=spec.dimension,
        event_id=event_id,
        dedupe_key=dedupe_key or f"{family}:{event_id}",
        source_path=spec.source_path,
        source_provider=spec.source_provider,
        quantity=quantity,
        package_id=package_id,
        billable=billable,
        enforce=enforce,
        raise_on_denied=raise_on_denied,
        raise_on_metering_error=raise_on_metering_error,
        entitlements=entitlements,
        metering=metering,
        evidence=evidence,
        metadata=metadata,
    )


__all__ = [
    # Family registry.
    "CAPABILITY_FAMILIES",
    "CapabilityFamily",
    "family_dimension",
    "is_known_family",
    "meter_family_usage",
    # Re-homed metering seam (was services/metering_evidence/hooks.py).
    "DUPLICATE",
    "ENTITLEMENT_DENIED",
    "METERED",
    "METERING_ERROR",
    "METERING_STATES",
    "MeteringStoreError",
    "MeterOutcome",
    "meter_capability_usage",
    # Re-homed entitlement enforcement seam (was services/capabilities/enforcement.py).
    "ENTITLEMENT_STATE_DENIED",
    "ENTITLEMENT_STATE_INCLUDED",
    "ENTITLEMENT_STATE_OVERAGE",
    "ENTITLEMENT_DENY_DISABLED",
    "ENTITLEMENT_DENY_NOT_ENTITLED",
    "ENTITLEMENT_DENY_OVERAGE_NOT_ALLOWED",
    "CapabilityEntitlementService",
    "EnforcementResult",
    "EntitlementDeniedError",
    "enforce_entitlement",
]
