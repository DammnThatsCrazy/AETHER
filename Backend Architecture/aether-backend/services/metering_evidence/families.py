"""Commercial capability-family registry for metering (§7).

Maps each commercial capability family to its canonical usage dimension and
default source path so capability-execution paths can meter with a one-line
call and never invent ad-hoc dimension strings. The integration pass wraps
each family's execution path with the matching ``meter_*_family`` helper
(see ``wiringNeeds`` in the program ledger); the registry here is the single
source of truth for the mapping so meter + reconciliation stay dimension-
aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from services.billing.revops import MeteringEventType

from .hooks import (
    MeterOutcome,
    meter_capability_usage,
)

# Canonical MeteringEventType values — guarantees every family maps onto a
# valid literal (fail-closed at the hook, before any write).
_VALID = frozenset(MeteringEventType.__args__)


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
    "CAPABILITY_FAMILIES",
    "CapabilityFamily",
    "family_dimension",
    "is_known_family",
    "meter_family_usage",
]
