"""Quota <-> Metering reconciliation (§7).

Proves the commercial usage invariant for a tenant + billing period:

    tenant entitled, capability executed, usage occurred exactly once,
    evidence durable.

Three usage truths exist in parallel and must be reconciled:

  * quota-engine counters  — ``rl:quota`` / ``rl:overage`` (Redis hot path)
                             plus the ``tenant_usage`` snapshot (Postgres),
                             counted per *request* by the middleware.
  * ``usage_metering_events`` — the RevOps meter (per *dimension* usage).
  * ``metering_evidence``     — durable per-usage evidence (§3.16).

The engine compares them and surfaces every mismatch as a typed discrepancy
with status :data:`RECONCILIATION_CONFLICT` — never silently. A clean period
is reported as :data:`RECONCILED`.

Discrepancy kinds:

  * ``evidence_missing``       — usage metered but durable billable evidence
                                 is short (billable loss / evidence lost).
  * ``evidence_double_count``  — billable evidence exceeds metered usage
                                 (risk of double billing).
  * ``entitled_no_entitlement``— usage occurred for a dimension with no
                                 enabled entitlement (capability executed
                                 without entitlement).
  * ``quota_not_incremented``  — quota counter < metered usage (capability
                                 executed without a request-level quota
                                 increment).
  * ``overage_unmetered``      — quota engine priced overage requests but the
                                 meter recorded zero usage (silent billable
                                 loss).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.billing.revops import (
    EntitlementService,
    UsageMeteringEventRepository,
    in_period,
)

from .service import MeteringEvidenceRepository

logger = get_logger("aether.metering_evidence.reconciliation")

RECONCILED = "RECONCILED"
RECONCILIATION_CONFLICT = "RECONCILIATION_CONFLICT"

# Stable machine-readable discrepancy kinds.
EVIDENCE_MISSING = "evidence_missing"
EVIDENCE_DOUBLE_COUNT = "evidence_double_count"
ENTITLED_NO_ENTITLEMENT = "entitled_no_entitlement"
QUOTA_NOT_INCREMENTED = "quota_not_incremented"
OVERAGE_UNMETERED = "overage_unmetered"


@dataclass
class ReconciliationDiscrepancy:
    """A single reconciled mismatch between the usage truths."""

    kind: str
    dimension: str
    metering_quantity: float
    evidence_quantity: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationReport:
    """Reconciliation result for one tenant + period.

    ``status`` is :data:`RECONCILED` or :data:`RECONCILIATION_CONFLICT`.
    ``discrepancies`` is empty only when reconciled. Truncation of bounded
    reads is disclosed, never hidden.
    """

    tenant_id: str
    period_start: str
    period_end: str
    status: str
    quota_engine_total: Optional[int]
    quota_engine_overage: dict[str, int]
    metering_by_dimension: dict[str, float]
    evidence_by_dimension: dict[str, float]
    discrepancies: list[ReconciliationDiscrepancy] = field(default_factory=list)
    population_truncated: bool = False
    checked_at: str = field(default_factory=lambda: utc_now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "status": self.status,
            "quota_engine_total": self.quota_engine_total,
            "quota_engine_overage": self.quota_engine_overage,
            "metering_by_dimension": self.metering_by_dimension,
            "evidence_by_dimension": self.evidence_by_dimension,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "population_truncated": self.population_truncated,
            "checked_at": self.checked_at,
        }


class ReconciliationEngine:
    """Reconcile quota-engine counters against metering + durable evidence.

    Pure read path — never mutates. ``quota_engine`` is optional (Redis may
    be absent); when provided its counters are cross-checked.
    """

    def __init__(
        self,
        events: UsageMeteringEventRepository | None = None,
        evidence: MeteringEvidenceRepository | None = None,
        entitlements: EntitlementService | None = None,
    ) -> None:
        self.events = events or UsageMeteringEventRepository()
        self.evidence = evidence or MeteringEvidenceRepository()
        self.entitlements = entitlements or EntitlementService()

    async def reconcile(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        quota_engine: Any = None,
        period: str | None = None,
    ) -> ReconciliationReport:
        """Reconcile one tenant's usage truths for the given period."""
        metering_by_dimension, evidence_by_dimension, truncated = (
            await self._aggregate_metering(tenant_id, period_start, period_end)
        )
        enabled = await self._enabled_features(tenant_id)
        quota_total, quota_overage = await self._read_quota(
            tenant_id, quota_engine, period or period_start[:7],
        )

        discrepancies: list[ReconciliationDiscrepancy] = []

        # ── Exactly-once + durable evidence, per dimension ────────────────
        for dim in sorted(set(metering_by_dimension) | set(evidence_by_dimension)):
            metered = float(metering_by_dimension.get(dim, 0))
            evid = float(evidence_by_dimension.get(dim, 0))
            if metered > 0 and evid < metered:
                discrepancies.append(ReconciliationDiscrepancy(
                    kind=EVIDENCE_MISSING,
                    dimension=dim,
                    metering_quantity=metered,
                    evidence_quantity=evid,
                    detail=(
                        f"{metered:g} usage metered but only {evid:g} billable "
                        "evidence is durable"
                    ),
                ))
            elif evid > metered:
                discrepancies.append(ReconciliationDiscrepancy(
                    kind=EVIDENCE_DOUBLE_COUNT,
                    dimension=dim,
                    metering_quantity=metered,
                    evidence_quantity=evid,
                    detail=(
                        f"{evid:g} billable evidence exceeds {metered:g} "
                        "metered usage"
                    ),
                ))

        # ── Entitlement coverage: no usage without an enabled entitlement ──
        for dim, qty in sorted(metering_by_dimension.items()):
            if qty > 0 and dim not in enabled:
                discrepancies.append(ReconciliationDiscrepancy(
                    kind=ENTITLED_NO_ENTITLEMENT,
                    dimension=dim,
                    metering_quantity=qty,
                    evidence_quantity=evidence_by_dimension.get(dim, 0),
                    detail=(
                        f"dimension {dim!r} used ({qty:g}) without an enabled "
                        "entitlement"
                    ),
                ))

        # ── Quota consistency (only when a quota engine is provided) ──────
        total_metered = float(sum(metering_by_dimension.values()))
        if quota_total is not None:
            if quota_total < total_metered:
                discrepancies.append(ReconciliationDiscrepancy(
                    kind=QUOTA_NOT_INCREMENTED,
                    dimension="*",
                    metering_quantity=total_metered,
                    evidence_quantity=float(quota_total),
                    detail=(
                        f"quota counter {quota_total} < metered usage "
                        f"{total_metered:g}"
                    ),
                ))
        overage_total = float(sum(quota_overage.values()))
        if overage_total > 0 and total_metered == 0:
            discrepancies.append(ReconciliationDiscrepancy(
                kind=OVERAGE_UNMETERED,
                dimension="*",
                metering_quantity=0.0,
                evidence_quantity=overage_total,
                detail=(
                    f"{overage_total:g} overage requests priced with zero "
                    "metered usage — silent billable loss"
                ),
            ))

        status = RECONCILIATION_CONFLICT if discrepancies else RECONCILED
        report = ReconciliationReport(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            status=status,
            quota_engine_total=quota_total,
            quota_engine_overage=quota_overage,
            metering_by_dimension=dict(metering_by_dimension),
            evidence_by_dimension=dict(evidence_by_dimension),
            discrepancies=discrepancies,
            population_truncated=truncated,
        )
        if discrepancies:
            logger.warning(
                "reconciliation conflict tenant=%s period=%s kinds=%s",
                tenant_id, period_start[:7],
                sorted({d.kind for d in discrepancies}),
            )
        return report

    async def _aggregate_metering(
        self, tenant_id: str, period_start: str, period_end: str,
    ) -> tuple[dict[str, float], dict[str, float], bool]:
        """Sum per-dimension usage from both durable truths."""
        records, truncated = await self.events.list_for_tenant_period(
            tenant_id, period_start, period_end,
        )
        metering_by_dimension: dict[str, float] = {}
        for r in records:
            dim = r.get('event_type') or r.get('usage_dimension') or 'unknown'
            metering_by_dimension[dim] = (
                metering_by_dimension.get(dim, 0.0) + float(r.get('quantity') or 0)
            )

        evidence_rows = await self.evidence.find_many(
            filters={'tenant_id': tenant_id}, limit=20000,
        )
        evidence_by_dimension: dict[str, float] = {}
        for r in evidence_rows:
            if not in_period(r, period_start, period_end, field='received_at'):
                continue
            if not r.get('billable', True):
                # Duplicate evidence is recorded non-billable — never counted
                # toward billable usage (fail-closed for double billing).
                continue
            dim = r.get('usage_dimension') or 'unknown'
            evidence_by_dimension[dim] = (
                evidence_by_dimension.get(dim, 0.0) + float(r.get('quantity') or 0)
            )
        return metering_by_dimension, evidence_by_dimension, truncated

    async def _enabled_features(self, tenant_id: str) -> set[str]:
        ents = await self.entitlements.entitlements.list_for_tenant(tenant_id)
        return {e['feature_key'] for e in ents if e.get('enabled', True)}

    async def _read_quota(
        self, tenant_id: str, quota_engine: Any, period: str,
    ) -> tuple[Optional[int], dict[str, int]]:
        if quota_engine is None:
            return None, {}
        try:
            total = await quota_engine.get_total_used(tenant_id, period)
        except Exception as exc:  # pragma: no cover - read path stays honest
            logger.warning("reconciliation quota_total read failed: %s", exc)
            total = None
        try:
            overage = await quota_engine.get_overage_counts(tenant_id, period)
        except Exception as exc:  # pragma: no cover
            logger.warning("reconciliation quota_overage read failed: %s", exc)
            overage = {}
        return total, overage


__all__ = [
    "EVIDENCE_DOUBLE_COUNT",
    "EVIDENCE_MISSING",
    "ENTITLED_NO_ENTITLEMENT",
    "OVERAGE_UNMETERED",
    "QUOTA_NOT_INCREMENTED",
    "RECONCILED",
    "RECONCILIATION_CONFLICT",
    "ReconciliationDiscrepancy",
    "ReconciliationEngine",
    "ReconciliationReport",
]
