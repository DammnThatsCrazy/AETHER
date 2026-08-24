"""Economic360 intelligence-projection provider (vertical slice S3).

Economic360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). This provider projects the *economic*
domain for a subject (campaign / episode / source) from canonical economic
facts: AI execution economics (``services/economic/ai_*``), computed campaign
economics (``services/economic/computed_results`` +
``services/computation/campaign``), value normalization / safe rollups
(``services/value``) and value diagnostics (``services/economic/value_diagnostics``).

The provider is a read-only, fail-isolated, tenant-scoped projection:

* It raises ONLY :class:`ProjectionError` subclasses on failure; the registry
  fail-isolates any other exception.
* It degrades sections (typed ``degraded`` / ``missing`` / ``empty`` states)
  instead of crashing or fabricating when a canonical source is unavailable.
* Every claim carries a reused canonical :class:`EvidenceRef`.
* Mixed-currency / missing-price / double-count situations produce the typed
  :class:`EconomicWarning` codes — never an invented USD figure.
* ``profile360`` / ``relationship360`` / ``outcome360`` are still ``in_flight``:
  the registry's ``build_context`` records them in ``dependencyState`` and this
  provider degrades the ``outcomes`` section honestly instead of raising.

Imports stay lazy/defensive: importing this module must never require a
database, a store backend, or any heavy canonical service. All canonical reads
happen inside :meth:`Economic360Provider.project` (and the injected source
reader), each wrapped so an unavailable backing source degrades its section.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol

# Lightweight plane imports — always importable.
from shared.intelligence_projections.contracts import (
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ClaimEnvelope,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry

# Reused canonical primitives (never redefined here).
from services.operational_intelligence.models import EvidenceRef

# Economic domain contracts for this slice.
from services.economic.economic360_contracts import (
    EconomicWarning,
    EconomicWarningCode,
    MonetaryAmount,
    detect_double_count,
    economic_warnings_for_amounts,
    safe_usd_total,
)

# Sections the registry declares for economic360 (must match outputSections).
OUTPUT_SECTIONS: tuple[str, ...] = ("summary", "state", "evidence", "outcomes", "findings")

# Registry projection dependencies we degrade for honestly while they are
# still in_flight (profile360 / relationship360 / outcome360). Each entry maps
# the section whose enrichment depends on that sibling projection.
SECTION_DEPENDENCIES: dict[str, str] = {
    "summary": "profile360",
    "state": "relationship360",
    "outcomes": "outcome360",
}


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EconomicSourceReader(Protocol):
    """Canonical economic read seam for the provider.

    Implementations MUST be tenant-scoped: the provider trusts nothing and
    re-filters every returned record by the requesting tenant. A reader that
    cannot reach its backing store returns ``[]`` (the provider degrades the
    affected sections) — never raises, never fabricates.
    """

    async def records(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical economic value records for the tenant + subject.

        Each record is a raw value-record shape consumed by
        ``services/value``'s ``value_of`` / ``safe_rollup`` (native ``amount`` /
        ``currency``, optional ``value_usd``, optional ``metric_kind``) plus
        ``tenant_id`` and ``_source`` / ``_evidence_*`` bookkeeping.
        """
        ...


class RepositoryEconomicSourceReader:
    """Default canonical reader over the existing ``services/economic`` stores.

    Reads AI execution facts (``ai_aggregation.list_facts``) and computed
    campaign economics (``ComputedResultsRepository``) defensively, mapping each
    to a raw value-record. Any backing-source failure returns ``[]`` for that
    source — the projection degrades, it never crashes.
    """

    async def records(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        records.extend(await self._ai_cost_records(tenant_id))
        records.extend(await self._computed_metric_records(tenant_id, subject))
        return records

    async def _ai_cost_records(self, tenant_id: str) -> list[dict[str, Any]]:
        """AI execution cost facts, mapped to value records (defensive)."""
        try:
            from services.economic import ai_aggregation

            facts = await ai_aggregation.list_facts(tenant_id, limit=500)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        records: list[dict[str, Any]] = []
        for fact in facts:
            if str(fact.get("tenant_id", "")) != tenant_id:
                continue
            selected = fact.get("selected_cost")
            if selected is None:
                # Unknown cost stays unknown — never coerced to a zero record.
                continue
            invocation_id = str(fact.get("invocation_id") or fact.get("_key") or "")
            records.append(
                {
                    "tenant_id": tenant_id,
                    "amount": selected,
                    "currency": fact.get("currency"),
                    "metric_kind": "cost",
                    "_source": "ai_execution_facts",
                    "_evidence_id": invocation_id,
                    "_evidence_type": "event",
                    "_evidence_source": "services/economic/ai_aggregation",
                    "_evidence_uri": f"store://ai_execution_facts/{invocation_id}",
                    "_metric_name": "campaign_spend",
                }
            )
        return records

    async def _computed_metric_records(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical computed campaign economics for the scope (defensive)."""
        try:
            from services.economic.computed_results import campaign_computation_context
            from services.computation.repositories import get_computation_repository

            ctx = campaign_computation_context(
                tenant_id,
                subject_type=subject.kind,
                subject_id=subject.id,
                event_time_start=None,
                event_time_end=None,
            )
            repo = get_computation_repository()
            rows = await repo.list_for_tenant(tenant_id, limit=200)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        records: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("tenant_id", "")) != tenant_id:
                continue
            value = row.get("value")
            if value is None:
                continue  # honest absence — never a fabricated zero record
            definition_id = str(row.get("definition_id") or "")
            result_id = str(row.get("result_id") or row.get("context_hash") or "")
            metric_name = "campaign_spend"
            if "gross_revenue" in definition_id or "revenue" in definition_id:
                metric_name = "gross_value"
            records.append(
                {
                    "tenant_id": tenant_id,
                    "amount": value,
                    "currency": row.get("currency"),
                    "metric_kind": "flow",
                    "_source": f"computed_results:{definition_id}",
                    "_evidence_id": result_id,
                    "_evidence_type": "model_output",
                    "_evidence_source": "services/economic/computed_results",
                    "_evidence_uri": f"store://computed_results/{definition_id}",
                    "_metric_name": metric_name,
                }
            )
        return records


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Parse a value into a Decimal, or None when unparseable (never 0)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return None


def _monetary_from_record(record: dict[str, Any]) -> MonetaryAmount:
    """A MonetaryAmount for a raw value record — absent USD stays None."""
    amount = _to_decimal(record.get("amount"))
    currency = record.get("currency")
    usd_value = _to_decimal(
        record.get("value_usd") or record.get("usd_value") or record.get("amount_usd")
    )
    return MonetaryAmount(
        amount=amount,
        currency=str(currency) if currency is not None else None,
        usd_value=usd_value,
    )


def _evidence_from_record(record: dict[str, Any]) -> Optional[EvidenceRef]:
    """A reused canonical EvidenceRef for a record (None when the record has none)."""
    evidence_id = record.get("_evidence_id")
    if not evidence_id:
        return None
    etype = str(record.get("_evidence_type") or "event")
    if etype not in {
        "event", "entity", "relationship", "document",
        "transaction", "model_output", "annotation",
    }:
        etype = "event"
    return EvidenceRef(
        id=str(evidence_id),
        type=etype,  # type: ignore[arg-type]
        source=str(record.get("_evidence_source") or "services/economic"),
        uri=record.get("_evidence_uri"),
    )


class Economic360Provider:
    """Intelligence-projection provider for ``economic360`` (read-only)."""

    projection_id = "economic360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, sources: Optional[EconomicSourceReader] = None) -> None:
        # Injected canonical reader (test seam); default reads repositories.
        self._sources = sources if sources is not None else RepositoryEconomicSourceReader()

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Economic360 projection over canonical Aether truth."""
        tenant_id = request.tenantId
        tenant_filtered: list[dict[str, Any]] = []
        records = await self._safe_records(tenant_id, request.subject)
        for record in records:
            # Tenant scope is server-authoritative: never project another
            # tenant's economic sections/evidence.
            if str(record.get("tenant_id", tenant_id)) == tenant_id:
                tenant_filtered.append(record)

        warnings = economic_warnings_for_amounts(
            _monetary_from_record(r) for r in tenant_filtered
        )

        # Canonical safe rollup + value diagnostics over the tenant's records.
        rollup = self._safe_rollup(tenant_filtered)
        diagnostic = self._diagnose(rollup)

        # Double-count detection over economic positions derived from records.
        warnings.extend(self._double_count_warnings(tenant_filtered, request))

        evidence = [
            ref
            for ref in (_evidence_from_record(r) for r in tenant_filtered)
            if ref is not None
        ]

        dep_state = context.dependencyState
        sections = [
            self._summary_section(request, tenant_filtered, rollup, dep_state),
            self._state_section(tenant_filtered, diagnostic, dep_state),
            self._evidence_section(evidence),
            self._outcomes_section(tenant_filtered, dep_state),
            self._findings_section(warnings, evidence),
        ]
        claims = self._build_claims(request, tenant_filtered, rollup, warnings, evidence)

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(dep_state),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        records: list[dict[str, Any]],
        rollup: dict[str, Any],
        dep_state: list[Any],
    ) -> ProjectionSection:
        """summary — total value observed + the campaign economic metric set."""
        state: str = "available"
        if not records:
            state = "missing"
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["summary"]):
            # profile360 is still in_flight: the summary is present but the
            # profile enrichment that would cross-reference it is not available.
            state = "degraded"
        elif rollup.get("rollup_status") in ("unavailable", "conflicted"):
            state = "degraded"

        spend_amounts = [
            _monetary_from_record(r)
            for r in records
            if r.get("_metric_name") == "campaign_spend"
        ]
        gross_amounts = [
            _monetary_from_record(r)
            for r in records
            if r.get("_metric_name") in ("gross_value", "revenue")
        ]
        spend_usd, _ = safe_usd_total(spend_amounts)
        gross_usd, _ = safe_usd_total(gross_amounts)
        roas: Optional[Decimal] = None
        if spend_usd is not None and gross_usd is not None and spend_usd != 0:
            roas = (gross_usd / spend_usd).quantize(Decimal("0.0001"))

        content: dict[str, Any] = {
            "tenantId": request.tenantId,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "total_usd": rollup.get("total_usd"),  # None preserved — never 0
            "native_currency": rollup.get("native_currency"),
            "native_total": rollup.get("native_total"),
            "rollup_status": rollup.get("rollup_status"),
            "metrics": {
                "campaign_spend": {
                    "unit": "usd",
                    "usd_value": None if spend_usd is None else format(spend_usd, "f"),
                    "state": "available" if spend_usd is not None else "missing",
                },
                "gross_value": {
                    "unit": "usd",
                    "usd_value": None if gross_usd is None else format(gross_usd, "f"),
                    "state": "available" if gross_usd is not None else "missing",
                },
                "campaign_roas": {
                    "unit": "ratio",
                    "value": None if roas is None else format(roas, "f"),
                    "state": "available" if roas is not None else "missing",
                },
                "campaign_cac": {
                    "unit": "usd",
                    "usd_value": None,
                    "state": "missing",  # not derivable without customer counts
                },
                "campaign_ltv": {
                    "unit": "usd",
                    "usd_value": None,
                    "state": "missing",
                },
            },
        }
        warnings: list[str] = []
        if state == "degraded" and _dependency_missing(
            dep_state, SECTION_DEPENDENCIES["summary"]
        ):
            warnings.append(
                "profile360 dependency not available; summary is degraded"
            )
        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Economic summary",
            content=content,
            warnings=warnings or None,
        )

    def _state_section(
        self,
        records: list[dict[str, Any]],
        diagnostic: dict[str, Any],
        dep_state: list[Any],
    ) -> ProjectionSection:
        """state — value diagnostics over the canonical rollup."""
        state: str = "available"
        if not records:
            state = "empty"
        elif _dependency_missing(dep_state, SECTION_DEPENDENCIES["state"]):
            # relationship360 is still in_flight: state diagnostics are present
            # but the relationship context that would enrich them is not.
            state = "degraded"
        elif diagnostic.get("valuation_status") in ("unavailable", "conflicted"):
            state = "degraded"
        warnings: list[str] = []
        if state == "degraded" and _dependency_missing(
            dep_state, SECTION_DEPENDENCIES["state"]
        ):
            warnings.append(
                "relationship360 dependency not available; state is degraded"
            )
        return ProjectionSection(
            id="state",
            state=state,  # type: ignore[arg-type]
            title="Economic state",
            content=diagnostic,
            warnings=warnings or None,
        )

    def _evidence_section(
        self,
        evidence: list[EvidenceRef],
    ) -> ProjectionSection:
        """evidence — the canonical evidence refs grounding this projection."""
        return ProjectionSection(
            id="evidence",
            state="available" if evidence else "empty",
            title="Evidence",
            content={
                "count": len(evidence),
                "evidence": [e.model_dump(mode="json") for e in evidence],
            },
        )

    def _outcomes_section(
        self,
        records: list[dict[str, Any]],
        dep_state: list[Any],
    ) -> ProjectionSection:
        """outcomes — outcome-economics, degraded honestly until outcome360 lands."""
        outcome = next(
            (d for d in dep_state if d.projectionId == SECTION_DEPENDENCIES["outcomes"]),
            None,
        )
        if not _dependency_missing(dep_state, SECTION_DEPENDENCIES["outcomes"]):
            state = "available"
            reason = None
        else:
            state = "degraded"
            reason = (
                "outcome360 dependency is not yet implemented; outcome "
                "economics are not projected (in_flight)"
            )
        gross_amounts = [
            _monetary_from_record(r)
            for r in records
            if r.get("_metric_name") in ("gross_value", "revenue")
        ]
        gross_usd, _ = safe_usd_total(gross_amounts)
        return ProjectionSection(
            id="outcomes",
            state=state,  # type: ignore[arg-type]
            title="Outcome economics",
            content={
                "dependencyState": {
                    "projectionId": "outcome360",
                    "state": "missing" if outcome is None else outcome.state,
                },
                "reason": reason,
                "outcome_value_usd": (
                    None if gross_usd is None else format(gross_usd, "f")
                ),
            },
            warnings=[reason] if reason else None,
        )

    def _findings_section(
        self,
        warnings: list[EconomicWarning],
        evidence: list[EvidenceRef],
    ) -> ProjectionSection:
        """findings — typed anti-pattern warnings, never invented values."""
        return ProjectionSection(
            id="findings",
            state="available",
            title="Economic findings",
            content={
                "warnings": [w.model_dump(mode="json") for w in warnings],
                "evidence_count": len(evidence),
            },
        )

    def _double_count_warnings(
        self,
        records: list[dict[str, Any]],
        request: ProjectionRequest,
    ) -> list[EconomicWarning]:
        """POSSIBLE_DOUBLE_COUNT warnings from derivative-receipt records.

        Records that carry ``_derivative_receipt`` + ``_underlying_position_id``
        are modeled as :class:`EconomicPosition` values and run through the
        typed double-count detector — never a fabricated figure.
        """
        flagged = [
            r
            for r in records
            if r.get("_derivative_receipt") or r.get("_underlying_position_id")
        ]
        if not flagged:
            return []
        from services.economic.economic360_contracts import EconomicPosition
        from services.operational_intelligence.models import EntityRef

        positions = [
            EconomicPosition(
                id=str(r.get("_evidence_id") or f"pos-{i}"),
                tenant_id=request.tenantId,
                holder=EntityRef(kind="economic_resource", id=request.subject.id),
                position_type="receipt" if r.get("_derivative_receipt") else "position",
                is_derivative_receipt=bool(r.get("_derivative_receipt")),
                underlying_position_id=r.get("_underlying_position_id"),
            )
            for i, r in enumerate(flagged)
        ]
        return detect_double_count(positions)

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        records: list[dict[str, Any]],
        rollup: dict[str, Any],
        warnings: list[EconomicWarning],
        evidence: list[EvidenceRef],
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims (requiresEvidence: every claim is grounded)."""
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)

        total_usd = rollup.get("total_usd")
        if total_usd is not None:
            claims.append(
                ClaimEnvelope(
                    id="summary.total_value_observed",
                    kind="economic_rollup",
                    subject=subject,
                    evidenceRefs=evidence,
                    claims=[
                        f"trusted USD total observed: ${total_usd}",
                        f"rollup status: {rollup.get('rollup_status')}",
                    ],
                )
            )
        else:
            unpriced_refs = evidence[:5]
            claims.append(
                ClaimEnvelope(
                    id="summary.no_trusted_total",
                    kind="economic_rollup",
                    subject=subject,
                    evidenceRefs=unpriced_refs,
                    claims=[
                        "no trusted USD total is available; unpriced amounts are "
                        "never coerced to zero"
                    ],
                )
            )

        spend_usd, _ = safe_usd_total(
            _monetary_from_record(r)
            for r in records
            if r.get("_metric_name") == "campaign_spend"
        )
        if spend_usd is not None:
            spend_refs = [
                ref
                for ref, r in zip(
                    (_evidence_from_record(r) for r in records),
                    records,
                )
                if ref is not None and r.get("_metric_name") == "campaign_spend"
            ]
            claims.append(
                ClaimEnvelope(
                    id="summary.campaign_spend",
                    kind="campaign_spend",
                    subject=subject,
                    evidenceRefs=spend_refs or evidence[:5],
                    claims=[
                        f"campaign spend (USD): {format(spend_usd, 'f')}"
                    ],
                )
            )

        for warning in warnings:
            claims.append(
                ClaimEnvelope(
                    id=f"findings.{warning.code.value.lower()}",
                    kind="economic_warning",
                    subject=subject,
                    evidenceRefs=evidence[:5],
                    claims=[warning.message],
                    confidence=None,
                )
            )

        return claims

    # ── Canonical read helpers (defensive) ─────────────────────────────────

    async def _safe_records(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[dict[str, Any]]:
        """Canonical records for the tenant; any reader failure degrades."""
        try:
            return await self._sources.records(
                tenant_id=tenant_id, subject=subject
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []

    def _safe_rollup(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Canonical safe rollup over value records (services/value semantics)."""
        try:
            from services.value.rollups import safe_rollup

            return safe_rollup(records, metric_kind="flow")
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return {
                "total_usd": None,
                "by_native_currency": {},
                "unpriced_count": 0,
                "stale_count": 0,
                "excluded_count": 0,
                "rollup_status": "unavailable",
                "native_currency": None,
                "native_total": None,
            }

    def _diagnose(self, rollup: dict[str, Any]) -> dict[str, Any]:
        """Value diagnostics over a rollup (services/economic/value_diagnostics)."""
        try:
            from services.economic.value_diagnostics import diagnose_rollup

            return diagnose_rollup(rollup)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return {
                "valuation_status": "unavailable",
                "total_usd": rollup.get("total_usd"),
                "has_trusted_total": rollup.get("total_usd") is not None,
            }


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Economic360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Economic360Provider(), source="services/economic")


__all__ = [
    "Economic360Provider",
    "EconomicSourceReader",
    "OUTPUT_SECTIONS",
    "RepositoryEconomicSourceReader",
    "SECTION_DEPENDENCIES",
    "register_provider",
]
