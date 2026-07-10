"""Derivatives reconciliation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from services.derivatives.models import PositionEpochState, PositionStatus


@dataclass(frozen=True)
class ReconciliationVarianceFact:
    tenant_id: str
    variance_type: str
    expected_value: Decimal
    observed_value: Decimal
    difference: Decimal
    severity: str
    status: str
    source_refs: tuple[str, ...]


def reconcile_position_size(
    *,
    computed: PositionEpochState,
    observed_size: Decimal,
    source_ref: str,
    tolerance: Decimal = Decimal("0.00000001"),
) -> ReconciliationVarianceFact | None:
    difference = computed.size - observed_size
    if abs(difference) <= tolerance:
        return None
    severity = "critical" if computed.status is PositionStatus.CLOSED and observed_size != 0 else "high"
    return ReconciliationVarianceFact(
        tenant_id=computed.tenant_id,
        variance_type="position_size_mismatch",
        expected_value=computed.size,
        observed_value=observed_size,
        difference=difference,
        severity=severity,
        status="variance_detected",
        source_refs=(source_ref,),
    )
