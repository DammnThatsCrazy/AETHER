"""Risk360 exposure builder — "risk of what" from the economic plane (Phase 5).

:class:`~services.risk360.contracts.ExposureAssessment` names what is at stake
(exposed assets / outcomes / populations) and its economic value. The Risk360
package **never owns economic truth**: it reads the shipped economic plane and
normalizes it into the exposure contract.

* **Economic records** come from the canonical economic360 read seam —
  :class:`services.economic.economic360_provider.EconomicSourceReader` (an
  ``async records(*, tenant_id, subject) -> list[dict]`` of raw value records) —
  rolled up with the canonical :func:`services.value.rollups.safe_rollup`
  (single-monolith reuse, never re-implemented).
* **Revenue adjustments** (the append-only ``revenue_adjustments`` ledger read
  by ``services/measurement/repositories/adjustment_repo.AdjustmentRepository``)
  are already-realized reversals. A caller who has netted them (via
  ``AdjustmentRepository.net_adjustment``/summation) may pass
  ``net_adjustment_usd``; the builder NETs gross exposure by realized reversals
  so the value genuinely still at stake is reported. An unpriced gross is never
  fabricated into a number by netting it.

Honesty contract
----------------

* ``economic_value.usd_value`` is ``None`` when the rollup is unpriced or
  unavailable — never coerced to ``0`` (``MonetaryAmount`` shares this rule).
* ``ExposureAssessment.claim_state`` is ``derived`` only when a priced magnitude
  was actually derived; an unpriced-but-labeled exposure carries labels and
  evidence but ``claim_state=unknown`` (no fabricated magnitude claim).
* Subject-scoped evidence refs are content-derived (no uuid/clock) so two equal
  economic snapshots produce equal evidence ids.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol, Sequence

from services.economic.economic360_contracts import MonetaryAmount
from services.operational_intelligence.models import EntityRef, EvidenceRef

from .contracts import EpistemicStatus, ExposureAssessment

# Lazy single-monolith reuse — imported inside functions so module import never
# depends on the value/economic plane at import time.


def _decimal(value: Any) -> Optional[Decimal]:
    """A Decimal for a str/int/Decimal, or None (never coerced from garbage)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - unpriced/unknown stays None
        return None


def _evidence_id(prefix: str, **content: Any) -> str:
    import hashlib
    import json

    payload = json.dumps(
        {prefix: True, **content}, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return f"ev_{hashlib.sha256(payload).hexdigest()[:20]}"


def exposure_from_rollup(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    rollup: Mapping[str, Any],
    subject_ref: Optional[EntityRef] = None,
    exposed_asset_labels: Sequence[str] = (),
    exposed_outcome_labels: Sequence[str] = (),
    exposed_population_labels: Sequence[str] = (),
    net_adjustment_usd: Optional[Decimal] = None,
) -> ExposureAssessment:
    """Build an :class:`ExposureAssessment` from a ``safe_rollup`` result.

    ``rollup`` is the canonical value-plane rollup dict (``total_usd``,
    ``rollup_status``, ``unpriced_count``, …). ``net_adjustment_usd`` nets
    already-realized revenue adjustments (refunds/chargebacks/losses) off the
    gross value genuinely still at stake, flooring at zero. An unpriced gross is
    never made into a number by netting it — no fabricated magnitude.
    """
    rollup_status = rollup.get("rollup_status") or "unavailable"
    gross_usd = _decimal(rollup.get("total_usd"))
    unpriced_count = rollup.get("unpriced_count") or 0
    evidence: list[EvidenceRef] = []

    usd_value = gross_usd
    if (
        gross_usd is not None
        and net_adjustment_usd is not None
        and net_adjustment_usd != 0
    ):
        adjusted = gross_usd + net_adjustment_usd
        usd_value = max(Decimal("0"), adjusted)
        evidence.append(
            EvidenceRef(
                id=_evidence_id(
                    "revenue_adjustment",
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    net=str(net_adjustment_usd),
                ),
                type="transaction",
                source="measurement.revenue_adjustments",
            )
        )

    if gross_usd is not None:
        evidence.append(
            EvidenceRef(
                id=_evidence_id(
                    "economic_rollup",
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                    total=str(gross_usd),
                    status=rollup_status,
                ),
                type="transaction",
                source="economic.safe_rollup",
            )
        )

    has_magnitude = usd_value is not None
    labels: list[str] = list(exposed_asset_labels)
    outcome_labels = list(exposed_outcome_labels)
    if net_adjustment_usd is not None and net_adjustment_usd != 0:
        outcome_labels.append("revenue_adjustments")
    if not has_magnitude and unpriced_count:
        outcome_labels.append("unpriced_economic_value")

    return ExposureAssessment(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_ref=subject_ref,
        exposed_asset_labels=labels,
        exposed_outcome_labels=outcome_labels,
        exposed_population_labels=list(exposed_population_labels),
        economic_value=MonetaryAmount(usd_value=usd_value),
        claim_state=(
            EpistemicStatus.DERIVED if has_magnitude else EpistemicStatus.UNKNOWN
        ),
        evidence_refs=evidence,
    )


class EconomicRecordsReader(Protocol):
    """Structural mirror of ``EconomicSourceReader.records`` (duck-typed)."""

    async def records(
        self, *, tenant_id: str, subject: Any
    ) -> list[dict[str, Any]]: ...


async def subject_exposure(
    economic_reader: EconomicRecordsReader,
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    subject_ref: Optional[EntityRef] = None,
    metric_kind: str = "flow",
    net_adjustment_usd: Optional[Decimal] = None,
) -> ExposureAssessment:
    """Fetch a subject's economic records and build its exposure assessment.

    Reads the economic360 reader seam, rolls the raw value records up with the
    canonical :func:`safe_rollup`, and builds the exposure. Any backing-source
    failure yields an unpriced exposure (``usd_value=None``) — never a fabricated
    number and never a raised projection.
    """
    from shared.intelligence_projections.contracts import ProjectionSubject
    from services.value.rollups import safe_rollup

    try:
        subject = ProjectionSubject(kind=subject_kind, id=subject_id)
        records = await economic_reader.records(tenant_id=tenant_id, subject=subject)
        rollup = safe_rollup(records or [], metric_kind=metric_kind)
    except Exception:  # noqa: BLE001 - economic reads degrade, never fabricate
        rollup = {
            "total_usd": None,
            "by_native_currency": {},
            "unpriced_count": 0,
            "stale_count": 0,
            "excluded_count": 0,
            "rollup_status": "unavailable",
            "native_currency": None,
            "native_total": None,
        }

    return exposure_from_rollup(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        subject_ref=subject_ref,
        rollup=rollup,
        net_adjustment_usd=net_adjustment_usd,
    )


__all__ = [
    "EconomicRecordsReader",
    "exposure_from_rollup",
    "subject_exposure",
]
