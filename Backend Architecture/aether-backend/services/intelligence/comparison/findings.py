"""Comparison findings lifecycle: create → disposition → handoff.

A finding is the contract ``ComparisonFinding`` plus engine-level fields
(``FindingRecord``): the causal-claim level, fact-linkage state, current
disposition, and disposition history. The 7 registry dispositions drive the
lifecycle; ``investigate`` hands off to the EXISTING investigation plane
(``services.investigation`` cases) and ``decide``/``act`` hand off to the
EXISTING OODA loop (``services.intelligence`` recommendations, which the
Outcome Ledger aggregates) — never a parallel finding or outcome system.

Causal-claim ladder rule: a finding's ``causal_claim`` can never exceed the
ceiling its evidence basis supports — correlated or temporal evidence is
never labeled as causation. Violations raise, they are not clamped silently.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import Field

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics

from services.intelligence.comparison.contracts import ComparisonFinding
from services.intelligence.comparison.generated_vocabulary import (
    CAUSAL_CLAIM_LEVELS,
    COMPARISON_DISPOSITIONS,
    FACT_LINKAGE_STATES,
)
from services.intelligence.comparison.store import ComparisonFindingRepository
from services.intelligence.comparison.watchlists import (
    NoiseDecision,
    WatchlistDefinition,
    apply_noise_controls,
)

logger = get_logger("aether.intelligence.comparison.findings")

_CLAIM_RANK: dict[str, int] = {c: i for i, c in enumerate(CAUSAL_CLAIM_LEVELS)}

# Evidence basis → highest causal-claim level that basis can ever support.
# The engine only produces observational/statistical evidence, so nothing in
# this module can mint "causally_supported" — that requires experimental
# evidence recorded by a plane that owns it.
EVIDENCE_CLAIM_CEILING: dict[str, str] = {
    "direct_observation": "observed",
    "statistical_correlation": "correlated",
    "temporal_association": "temporally_associated",
    "attribution_model": "attributed",
    "model_inference": "inferred",
    "counterfactual_scenario": "counterfactual_estimate",
    "controlled_experiment": "causally_supported",
}


class CausalClaimViolation(ValueError):
    """A causal claim exceeded what its evidence basis supports."""


def validate_causal_claim(causal_claim: str, evidence_basis: str) -> None:
    if causal_claim not in CAUSAL_CLAIM_LEVELS:
        raise CausalClaimViolation(f"Unknown causal claim level: {causal_claim!r}")
    ceiling = EVIDENCE_CLAIM_CEILING.get(evidence_basis)
    if ceiling is None:
        raise CausalClaimViolation(f"Unknown evidence basis: {evidence_basis!r}")
    if _CLAIM_RANK[causal_claim] > _CLAIM_RANK[ceiling]:
        raise CausalClaimViolation(
            f"Evidence basis {evidence_basis!r} supports at most {ceiling!r}; "
            f"labeling it {causal_claim!r} is not allowed"
        )


class FindingRecord(ComparisonFinding):
    """Contract finding + engine lifecycle fields (superset, parity intact)."""

    causal_claim: str
    evidence_basis: str
    fact_linkage: str
    disposition: str = "informational"
    disposition_history: list[dict[str, Any]] = Field(default_factory=list)
    watchlist_id: Optional[str] = None

    def model_post_init(self, __context) -> None:  # noqa: D105
        if self.fact_linkage not in FACT_LINKAGE_STATES:
            raise ValueError(f"Unknown fact linkage state: {self.fact_linkage!r}")
        if self.disposition not in COMPARISON_DISPOSITIONS:
            raise ValueError(f"Unknown disposition: {self.disposition!r}")
        validate_causal_claim(self.causal_claim, self.evidence_basis)


class FindingsService:
    """Persistence + lifecycle over the findings JSONB store."""

    def __init__(self, repo: Optional[ComparisonFindingRepository] = None) -> None:
        self._repo = repo or ComparisonFindingRepository()

    # ── Creation (engine-facing) ─────────────────────────────────────────

    async def create(
        self,
        finding: FindingRecord,
        *,
        definition_id: str,
        watchlists: list[WatchlistDefinition],
    ) -> tuple[dict[str, Any], NoiseDecision]:
        """Persist a finding after watchlist noise controls.

        A suppressed finding is STILL persisted (disposition ``suppressed``
        with its typed ``suppression_reason``) so noise is auditable — it is
        just not surfaced as actionable.
        """
        recent = await self._repo.list_scoped(
            finding.tenant_id, {"comparison_run_definition_id": definition_id}, limit=200
        )
        payload = finding.model_dump(mode="json")
        decision = apply_noise_controls(watchlists, definition_id, payload, recent)
        if not decision.allowed:
            payload["disposition"] = "suppressed"
            payload["suppression_reason"] = decision.suppression_reason
            payload["watchlist_id"] = decision.watchlist_id
            metrics.increment(
                "comparison_findings_suppressed_total",
                labels={"reason": (decision.suppression_reason or "unknown").split(":")[0]},
            )
        payload["comparison_run_definition_id"] = definition_id
        stored = await self._repo.upsert_scoped(finding.tenant_id, finding.id, payload)
        metrics.increment(
            "comparison_findings_total",
            labels={"severity": str(finding.severity or "unscored")},
        )
        return stored, decision

    # ── Reads ────────────────────────────────────────────────────────────

    async def get(self, tenant_id: str, finding_id: str) -> dict[str, Any]:
        record = await self._repo.get_scoped(tenant_id, finding_id)
        if record is None:
            raise NotFoundError("comparison finding")
        return _restore_contract_id(record)

    async def list(
        self,
        tenant_id: str,
        *,
        run_id: Optional[str] = None,
        disposition: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        extra: dict[str, Any] = {}
        if run_id:
            extra["comparison_run_id"] = run_id
        if disposition:
            if disposition not in COMPARISON_DISPOSITIONS:
                raise BadRequestError(f"Unknown disposition {disposition!r}")
            extra["disposition"] = disposition
        if severity:
            extra["severity"] = severity
        rows = await self._repo.list_scoped(tenant_id, extra, limit=limit, offset=offset)
        return [_restore_contract_id(r) for r in rows]

    # ── Disposition lifecycle ────────────────────────────────────────────

    async def dispose(
        self,
        tenant_id: str,
        finding_id: str,
        disposition: str,
        *,
        actor_id: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Apply one of the 7 registry dispositions with typed handoffs."""
        if disposition not in COMPARISON_DISPOSITIONS:
            raise BadRequestError(
                f"Unknown disposition {disposition!r}; "
                f"expected one of {list(COMPARISON_DISPOSITIONS)}"
            )
        record = await self._repo.get_scoped(tenant_id, finding_id)
        if record is None:
            raise NotFoundError("comparison finding")

        patch: dict[str, Any] = {
            "disposition": disposition,
            "recommended_disposition": record.get("recommended_disposition"),
            "disposition_history": [
                *record.get("disposition_history", []),
                {
                    "disposition": disposition,
                    "actor_id": actor_id,
                    "reason": reason,
                    "at": utc_now().isoformat(),
                },
            ],
        }

        if disposition == "investigate" and not record.get("investigation_id"):
            patch["investigation_id"] = await self._open_investigation(record, actor_id)
        if disposition in ("decide", "act") and not record.get("recommendation_id"):
            recommendation_id = await self._emit_recommendation(record)
            if recommendation_id:
                patch["recommendation_id"] = recommendation_id

        updated = await self._repo.update_scoped(tenant_id, finding_id, patch)
        assert updated is not None  # existence checked above
        metrics.increment(
            "comparison_finding_dispositions_total", labels={"disposition": disposition}
        )
        return _restore_contract_id(updated)

    # ── Handoffs to existing planes ──────────────────────────────────────

    async def _open_investigation(self, finding: dict[str, Any], actor_id: str) -> str:
        """Create a case on the EXISTING investigation plane and link it."""
        from repositories.repos import InvestigationRepository

        case_id = str(uuid.uuid4())
        now = utc_now().isoformat()
        subjects = [
            {"id": ref, "type": "entity", "label": None}
            for ref in (finding.get("subject_refs") or [])
        ]
        case = {
            "id": case_id,
            "tenantId": finding.get("tenant_id"),
            "tenant_id": finding.get("tenant_id"),
            "title": finding.get("title")
            or f"Comparison finding {finding.get('finding_id') or finding.get('id')}",
            "status": "open",
            "subjects": subjects,
            "graphStateId": None,
            "evidence": [],
            "annotations": [],
            "createdBy": actor_id,
            "createdAt": now,
            "updatedAt": now,
        }
        await InvestigationRepository().create(case)
        metrics.increment("comparison_finding_investigations_total")
        logger.info(
            "comparison_finding_investigation_opened",
            extra={"case_id": case_id, "finding_id": finding.get("finding_id")},
        )
        return case_id

    async def _emit_recommendation(self, finding: dict[str, Any]) -> Optional[str]:
        """Generate an OODA recommendation for the finding's first subject.

        Uses the EXISTING recommendation engine + store, so decisions,
        actions, and outcomes flow through the Outcome Ledger unchanged.
        Findings without an entity subject cannot enter the entity OODA loop;
        that is reported honestly (no recommendation id) rather than invented.
        """
        subject_refs = finding.get("subject_refs") or []
        if not subject_refs:
            logger.info(
                "comparison_finding_no_subject_for_recommendation",
                extra={"finding_id": finding.get("finding_id")},
            )
            return None
        from services.intelligence.ooda_engine import GraphNativeRecommendationEngine
        from services.intelligence.repositories import RecommendationRepository

        engine = GraphNativeRecommendationEngine()
        signals = {
            "comparison_finding_id": finding.get("finding_id") or finding.get("id"),
            "dimension": finding.get("dimension"),
            "severity": finding.get("severity"),
            "materiality": finding.get("materiality"),
            "causal_claim": finding.get("causal_claim"),
        }
        candidates = engine.generate_all_for_entity(
            str(finding.get("tenant_id")), str(subject_refs[0]), signals
        )
        if not candidates:
            logger.info(
                "comparison_finding_no_recommendation_family_matched",
                extra={"finding_id": finding.get("finding_id")},
            )
            return None
        recommendation = candidates[0].model_dump()
        await RecommendationRepository().insert(
            recommendation["recommendation_id"], recommendation
        )
        metrics.increment("comparison_finding_recommendations_total")
        return recommendation["recommendation_id"]


def _restore_contract_id(record: dict[str, Any]) -> dict[str, Any]:
    """Findings store their natural id under ``finding_id``; the contract
    field is ``id`` — restore it on the way out."""
    if "finding_id" in record:
        record = {**record, "id": record["finding_id"]}
    return record


__all__ = [
    "EVIDENCE_CLAIM_CEILING",
    "CausalClaimViolation",
    "FindingRecord",
    "FindingsService",
    "validate_causal_claim",
]
