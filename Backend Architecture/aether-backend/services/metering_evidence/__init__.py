"""Metering evidence service (§3.16) + metering/reconciliation (§7).

New, additive service. Wires nothing into the app itself — see ``routes.py``
for the optional read-only router. The §7 capability metering hook
(``hooks.py``), capability-family registry (``families.py``), and
quota<->metering reconciliation engine (``reconciliation.py``) live here too.
"""
from __future__ import annotations

from .families import (
    CAPABILITY_FAMILIES,
    CapabilityFamily,
    family_dimension,
    is_known_family,
    meter_family_usage,
)
from .hooks import (
    DUPLICATE,
    ENTITLEMENT_DENIED,
    METERED,
    METERING_ERROR,
    METERING_STATES,
    MeteringStoreError,
    MeterOutcome,
    meter_capability_usage,
)
from .reconciliation import (
    EVIDENCE_DOUBLE_COUNT,
    EVIDENCE_MISSING,
    ENTITLED_NO_ENTITLEMENT,
    OVERAGE_UNMETERED,
    QUOTA_NOT_INCREMENTED,
    RECONCILED,
    RECONCILIATION_CONFLICT,
    ReconciliationDiscrepancy,
    ReconciliationEngine,
    ReconciliationReport,
)
from .service import (
    EXCLUDED_DUPLICATE,
    MeteredEvent,
    MeteringEvidenceRepository,
    MeteringEvidenceService,
)

__all__ = [
    "CAPABILITY_FAMILIES",
    "DUPLICATE",
    "ENTITLEMENT_DENIED",
    "EVIDENCE_DOUBLE_COUNT",
    "EVIDENCE_MISSING",
    "ENTITLED_NO_ENTITLEMENT",
    "EXCLUDED_DUPLICATE",
    "METERED",
    "METERING_ERROR",
    "METERING_STATES",
    "OVERAGE_UNMETERED",
    "QUOTA_NOT_INCREMENTED",
    "RECONCILED",
    "RECONCILIATION_CONFLICT",
    "CapabilityFamily",
    "MeteredEvent",
    "MeteringEvidenceRepository",
    "MeteringEvidenceService",
    "MeteringStoreError",
    "MeterOutcome",
    "ReconciliationDiscrepancy",
    "ReconciliationEngine",
    "ReconciliationReport",
    "family_dimension",
    "is_known_family",
    "meter_capability_usage",
    "meter_family_usage",
]
