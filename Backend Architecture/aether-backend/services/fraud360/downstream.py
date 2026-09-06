"""Fraud360 Phase-6 downstream — material-hypothesis → comparison-finding handoff.

Phase 6 hands MATERIAL fraud hypotheses into the EXISTING intelligence
comparison-findings plane (``services/intelligence/comparison``) so actionable
fraud suspicion joins the same noise-controlled, disposition-driven finding
lifecycle every other intelligence lens uses. This module is a projection, not
a parallel finding system: it creates :class:`FindingRecord`(s) through
:class:`FindingsService` — never a second outcome ledger.

Honesty contract
----------------

* :func:`hypothesis_to_finding_candidate` returns a candidate ONLY for a
  *material* hypothesis (state in ``material`` / ``investigating`` /
  ``confirmed``) whose claim state maps to a real evidence basis. A
  ``candidate``-state suspicion is not yet material and yields ``None``; a claim
  state with no honest causal claim (``unknown`` / ``unavailable`` /
  ``not_applicable``) yields ``None`` too — nothing is fabricated into a finding.
* The finding's ``causal_claim`` is capped by its ``evidence_basis`` per the
  generated-vocabulary ceiling (``validate_causal_claim``): a ``derived`` /
  ``inferred`` suspicion maps to ``model_inference`` → ``inferred`` (never
  ``causally_supported``). The comparison-plane materiality scorer is NOT
  called here — the fraud hypothesis carries its own honest materiality.
* Suppression is never silent: :func:`material_hypotheses_to_findings` counts
  noise-suppressed findings separately and records each hypothesis's outcome.
  When the comparison plane is disabled it returns an honest skipped envelope
  — it does not "fall back" to writing findings anyway.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from services.fraud360.contracts import (
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
)
from services.intelligence.comparison.findings import FindingRecord
from services.intelligence.comparison.watchlists import WatchlistDefinition

#: hypothesis states treated as material for the downstream handoff (mirrors the
#: provider's ``_MATERIAL_HYPOTHESIS_STATES`` — a ``candidate`` suspicion is not
#: yet a finding).
_MATERIAL_HYPOTHESIS_STATES: frozenset[FraudHypothesisState] = frozenset(
    {
        FraudHypothesisState.MATERIAL,
        FraudHypothesisState.INVESTIGATING,
        FraudHypothesisState.CONFIRMED,
    }
)

#: Fraud-plane findings carry no comparison run; ``comparison_run_id`` is
#: required on the finding contract, so downstream findings record the honest
#: sentinel (they are grouped under ``definition_id`` instead).
_NO_COMPARISON_RUN = ""

#: Comparison dimension a fraud handoff projects onto (registry member).
_FRAUD_DIMENSION = "fraud_risk"

#: Finding type tag for fraud-plane material-hypothesis handoffs.
FINDING_TYPE = "fraud360_material_hypothesis"

#: Disabled-plane envelope (honest skip — never an implicit enable).
DISABLED_ENVELOPE: dict[str, Any] = {
    "created": 0,
    "suppressed": 0,
    "skipped_reason": "comparison plane disabled",
    "records": [],
}

#: Epistemic claim → (evidence basis, ceiling causal claim) honest projection.
#: Every pair sits AT its evidence-basis ceiling (never above), so a constructed
#: FindingRecord always passes ``validate_causal_claim``.
_CLAIM_EVIDENCE_MAP: dict[EpistemicStatus, tuple[str, str]] = {
    EpistemicStatus.DERIVED: ("model_inference", "inferred"),
    EpistemicStatus.INFERRED: ("model_inference", "inferred"),
    EpistemicStatus.PREDICTED: ("model_inference", "inferred"),
    EpistemicStatus.CORRELATED: ("statistical_correlation", "correlated"),
    EpistemicStatus.ATTRIBUTED: ("attribution_model", "attributed"),
    EpistemicStatus.OBSERVED: ("direct_observation", "observed"),
    EpistemicStatus.VERIFIED: ("direct_observation", "observed"),
    EpistemicStatus.RESOLVED: ("direct_observation", "observed"),
    EpistemicStatus.CAUSALLY_SUPPORTED: ("controlled_experiment", "causally_supported"),
}


def _finding_id(hypothesis: FraudHypothesis) -> str:
    """Deterministic, content-derived finding id (idempotent re-materialization).

    A re-run over the same hypothesis maps to the same finding row, so the
    findings service upserts rather than forking a duplicate.
    """
    digest = hashlib.sha256(
        f"{hypothesis.tenant_id}|{hypothesis.hypothesis_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"ff_{digest}"


def _severity_for_materiality(materiality: Optional[float]) -> Optional[str]:
    """Honest severity ladder over the hypothesis's OWN materiality (or None)."""
    if materiality is None:
        return None
    if materiality >= 0.7:
        return "critical"
    if materiality >= 0.5:
        return "high"
    if materiality >= 0.3:
        return "medium"
    if materiality >= 0.1:
        return "low"
    return "info"


def _recommended_disposition(
    severity: Optional[str],
    policy_row_or_outcome: Any = None,
) -> Optional[str]:
    """Registry disposition for a candidate.

    When a caller projects a real ``PolicyOutcome`` (from a decision policy the
    fraud finding inherits) an action outcome recommends ``investigate``; there
    is no fraud-specific policy, so by default the recommendation follows the
    severity ladder exactly like the comparison engine's own helper.
    """
    if policy_row_or_outcome is not None:
        try:
            from shared.computation.policies import PolicyOutcome

            if isinstance(policy_row_or_outcome, PolicyOutcome):
                return {
                    PolicyOutcome.BLOCK: "investigate",
                    PolicyOutcome.INTERVENE: "investigate",
                    PolicyOutcome.REJECT: "investigate",
                    PolicyOutcome.MERGE: "investigate",
                    PolicyOutcome.REVIEW: "monitor",
                    PolicyOutcome.ALLOW: "informational",
                    PolicyOutcome.IGNORE: "informational",
                }.get(policy_row_or_outcome)
        except Exception:  # noqa: BLE001 - never fail a handoff on an odd outcome
            pass
    return {
        "info": "informational",
        "low": "monitor",
        "medium": "monitor",
        "high": "investigate",
        "critical": "investigate",
    }.get(severity or "")


def hypothesis_to_finding_candidate(
    hypothesis: FraudHypothesis,
    *,
    policy_row_or_outcome: Any = None,
) -> Optional[dict[str, Any]]:
    """Project ONE material hypothesis into a finding-candidate dict, else None.

    Returns None when the hypothesis is not material (still ``candidate`` /
    ``under_evaluation`` / ``supported``), or when its claim state has no honest
    causal-claim projection (``unknown`` / ``unavailable`` / ``not_applicable``
    / meta states) — such a hypothesis is not fabricated into a finding.
    """
    if hypothesis.state not in _MATERIAL_HYPOTHESIS_STATES:
        return None
    pair = _CLAIM_EVIDENCE_MAP.get(hypothesis.claim_state)
    if pair is None:
        return None
    evidence_basis, causal_claim = pair

    materiality = hypothesis.materiality
    severity = _severity_for_materiality(materiality)
    recommended = _recommended_disposition(severity, policy_row_or_outcome)
    evidence_ref_count = len(hypothesis.evidence_refs or [])
    authority_ids = (
        len(hypothesis.risk_assessment_ids or [])
        + len(hypothesis.network_ids or [])
        + len(hypothesis.flow_trace_ids or [])
        + len(hypothesis.decision_ids or [])
    )
    subject_refs = (
        [hypothesis.subject_id] if hypothesis.subject_kind == "entity" else None
    )
    pattern_ids = ", ".join(hypothesis.matched_pattern_ids or ["<none>"])
    narrative = (
        f"Material fraud hypothesis {hypothesis.hypothesis_id} for "
        f"{hypothesis.subject_kind}:{hypothesis.subject_id} reached state "
        f"{hypothesis.state.value!r} under claim_state "
        f"{hypothesis.claim_state.value!r}. Evidence basis {evidence_basis!r} "
        f"supports at most the {causal_claim!r} causal-claim level. "
        f"Matched pattern(s): {pattern_ids}. Grounded in {evidence_ref_count} "
        f"evidence ref(s) across {authority_ids} authority id(s)."
    )

    return {
        "id": _finding_id(hypothesis),
        "comparison_run_id": _NO_COMPARISON_RUN,
        "tenant_id": hypothesis.tenant_id,
        "finding_type": FINDING_TYPE,
        "title": (
            f"Material fraud hypothesis: {hypothesis.matched_pattern_ids[0]}"
            if hypothesis.matched_pattern_ids
            else "Material fraud hypothesis"
        ),
        "narrative": narrative,
        "subject_refs": subject_refs,
        "dimension": _FRAUD_DIMENSION,
        "metric": (
            hypothesis.matched_pattern_ids[0]
            if hypothesis.matched_pattern_ids
            else None
        ),
        "materiality": materiality,
        "confidence": hypothesis.confidence,
        "severity": severity,
        "recommended_disposition": recommended,
        "evidence_status": hypothesis.claim_state.value,
        "first_observed_at": hypothesis.created_at,
        "last_observed_at": hypothesis.updated_at or hypothesis.created_at,
        "causal_claim": causal_claim,
        "evidence_basis": evidence_basis,
        "fact_linkage": "linked" if evidence_ref_count else "pending",
        # disposition defaults to "informational" on the FindingRecord; noise
        # controls may suppress (still persisted) before it is surfaced.
    }


async def material_hypotheses_to_findings(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    hypothesis_repo: Optional[Any] = None,
    findings_service: Optional[Any] = None,
    definition_id: str,
    watchlists: list[WatchlistDefinition],
    enabled: bool,
) -> dict[str, Any]:
    """Hand a subject's material fraud hypotheses into the findings plane.

    ``enabled=False`` returns the honest skipped envelope
    (:data:`DISABLED_ENVELOPE`) — findings are NEVER written while the
    comparison plane is disabled. When enabled, every material hypothesis for
    the subject is projected through :func:`hypothesis_to_finding_candidate`
    and created via :class:`FindingsService` under ``definition_id`` with the
    supplied ``watchlists`` (noise controls still persist suppressed findings —
    nothing is dropped silently).

    The returned envelope records each hypothesis's outcome:
    ``created`` / ``suppressed`` (persisted, noise-suppressed) / ``skipped``
    (not material or no honest causal projection) / ``error``.
    """
    if not enabled:
        return dict(DISABLED_ENVELOPE)

    from services.fraud360.store import FraudHypothesisRepository
    from services.intelligence.comparison.findings import FindingsService

    hypothesis_repo = hypothesis_repo or FraudHypothesisRepository()
    findings_service = findings_service or FindingsService()

    rows = await hypothesis_repo.list(tenant_id, limit=500)
    material = [
        h
        for h in rows
        if h.subject_kind == subject_kind
        and h.subject_id == subject_id
        and h.state in _MATERIAL_HYPOTHESIS_STATES
    ]

    created = 0
    suppressed = 0
    skipped = 0
    errors = 0
    records: list[dict[str, Any]] = []
    for hypothesis in sorted(material, key=lambda h: h.hypothesis_id):
        candidate = hypothesis_to_finding_candidate(hypothesis)
        if candidate is None:
            skipped += 1
            records.append(
                {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "outcome": "skipped",
                    "detail": "not a material candidate for a finding",
                }
            )
            continue
        try:
            finding = FindingRecord(**candidate)
            stored, decision = await findings_service.create(
                finding,
                definition_id=definition_id,
                watchlists=watchlists,
            )
            outcome = "created" if decision.allowed else "suppressed"
            if decision.allowed:
                created += 1
            else:
                suppressed += 1
            records.append(
                {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "finding_id": stored.get("finding_id")
                    or stored.get("id")
                    or candidate["id"],
                    "outcome": outcome,
                    "disposition": stored.get("disposition"),
                    "suppression_reason": stored.get("suppression_reason"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one bad handoff must not stop the rest
            errors += 1
            records.append(
                {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "outcome": "error",
                    "error": str(exc),
                }
            )

    return {
        "created": created,
        "suppressed": suppressed,
        "skipped": skipped,
        "errors": errors,
        "records": records,
    }


async def dispose_finding(
    tenant_id: str,
    finding_id: str,
    disposition: str,
    *,
    actor_id: str,
    reason: Optional[str] = None,
    findings_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply one of the registry dispositions to a downstream finding.

    Thin delegation to :meth:`FindingsService.dispose` (typed registry
    dispositions with investigation/OODA handoffs) — never a parallel
    disposition lifecycle.
    """
    from services.intelligence.comparison.findings import FindingsService

    service = findings_service or FindingsService()
    return await service.dispose(
        tenant_id,
        finding_id,
        disposition,
        actor_id=actor_id,
        reason=reason,
    )


__all__ = [
    "DISABLED_ENVELOPE",
    "FINDING_TYPE",
    "dispose_finding",
    "hypothesis_to_finding_candidate",
    "material_hypotheses_to_findings",
]
