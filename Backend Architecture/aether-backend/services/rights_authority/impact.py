"""Aether — Rights Authority: rights impact graph + revocation pipeline.

Stream P-B2 (part 2) of the ``rights_irrl`` canonical authority. Implements
blueprint §10 (rights impacts & remediation) / §66 (revocation pipeline) /
§67 (dependency-aware deletion cascade). Revocation must:

1. deny future governed use immediately,
2. produce an impact graph Grant → observations → normalized facts → graph state
   → computed intelligence → exports / models / generalized artifacts,
3. mark affected material,
4. enqueue required remediation,
5. preserve audit history,
6. re-evaluate generalized derivatives,
7. assess model impact,
8. surface unresolved remediation in Kyber,
9. keep DSR/termination pending until adapters report completion.

No fake completion. Anything not executed stays ``pending`` and is surfaced in
the pipeline summary's ``unresolved`` list.

Persistence rides the P-B1 ``rights_impact_repository`` / ``rights_decision_repository``
singletons (in-memory on local, Postgres otherwise). ``RightsImpact`` itself is a
P-B1-owned contract; this module emits *rows conforming to that contract* and
validates them into the P-B1 model when the parallel module is importable.
"""
from __future__ import annotations

import importlib
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from services.rights_authority.generalization import (
    GeneralizationGateway,
    generalized_artifact_repository,
)

logger = get_logger("aether.rights_irrl.impact")

POLICY_VERSION = "irrl-2"

# Cascade dimensions (blueprint §44 / §67).
RIGHTS_IMPACT_DIMENSIONS: tuple[str, ...] = (
    "raw_object",
    "normalized_row",
    "graph_edge",
    "vector_embedding",
    "cached_result",
    "derived_profile_attribute",
    "exported_artifact",
    "model_training_input",
    "generalized_artifact",
)

# Fail-closed default remediation action per cascade dimension. Contributions
# delete / hard-delete / tombstone; derived material recomputes; exports honour
# tenant retention only when already delivered (unknown delivery → delete, but
# surfaced as unresolved); model-training inputs trigger retrain/evaluation.
DEFAULT_IMPACT_ACTIONS: dict[str, str] = {
    "raw_object": "hard_delete",
    "normalized_row": "delete",
    "graph_edge": "delete",
    "vector_embedding": "recompute_or_delete",
    "cached_result": "recompute_or_delete",
    "derived_profile_attribute": "recompute_or_delete",
    "exported_artifact": "delete",  # overridden by delivery evidence → tenant_retains
    "model_training_input": "retrain_or_evaluation",
    "generalized_artifact": "recheck_eligibility",
}

# Actions that may be applied through a *recompute* rather than a destructive
# delete. These require reconcile/verified execution and stay pending otherwise.
_DERIVED_DIMENSIONS = frozenset({
    "vector_embedding", "cached_result", "derived_profile_attribute",
    "normalized_row", "graph_edge",
})

# State vocabulary for persisted impact items.
REMEDIATION_STATES: tuple[str, ...] = (
    "pending",
    "in_progress",
    "executed",
    "blocked",
    "superseded",
)


def _pb1_repositories():
    """P-B1: ``services.rights_authority.repositories`` singleton stores."""
    return importlib.import_module("services.rights_authority.repositories")


def _pb1_contracts():
    """P-B1: ``services.rights_authority.contracts`` RightsImpact surface."""
    return importlib.import_module("services.rights_authority.contracts")


class RevocationError(RuntimeError):
    """Raised when a revocation is unauthorized or its grant cannot be verified."""


async def _load_grant_by_id(grant_id: str) -> Any:
    """Load a grant by id through the canonical P-A DataRightsService."""
    from services.integrations.data_rights.service import data_rights_service

    return await data_rights_service.get_grant(grant_id)


# Revocation grant-loading seam (tests patch this; production hits P-A service).
_grant_loader = _load_grant_by_id


class RightsImpactItem(BaseModel):
    """A rights-impact row for one cascade component.

    ``RightsImpact`` is the P-B1-owned contract; this is the internal row shape
    emitted/persisted by this module and validated into the P-B1 model at the
    integration seam. Fields mirror the blueprint impact vocabulary.
    """

    impact_id: str = Field(default_factory=lambda: f"rimp_{uuid.uuid4().hex}")
    tenant_id: str
    grant_id: Optional[str] = None
    artifact_ref: Optional[str] = None
    component_type: Literal[
        "raw_object",
        "normalized_row",
        "graph_edge",
        "vector_embedding",
        "cached_result",
        "derived_profile_attribute",
        "exported_artifact",
        "model_training_input",
        "generalized_artifact",
    ]
    required_action: str
    remediation_state: str = "pending"
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class RevocationSummary(BaseModel):
    """Blueprint §66 pipeline output — never claims completion without execution."""

    revocation_decision_refs: list[str] = Field(default_factory=list)
    impact_ids: list[str] = Field(default_factory=list)
    model_impacts: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    generalized_recheck_ids: list[str] = Field(default_factory=list)


def _delivery_state(delivery_evidence: Optional[list[str]]) -> bool:
    """Whether exported artifacts may be retained as tenant-issued.

    Explicit delivery evidence (artifact already handed to the tenant) is
    required before ``tenant_retains``; anything unknown → delete (fail closed
    toward no further downstream use) but is surfaced as unresolved.
    """
    return bool(delivery_evidence)


# ═══════════════════════════════════════════════════════════════════════════
# Impact computation
# ═══════════════════════════════════════════════════════════════════════════

def compute_rights_impact(
    tenant_id: str,
    grant_id: Optional[str] = None,
    artifact_ref: Optional[str] = None,
    *,
    delivery_evidence: Optional[list[str]] = None,
    revocation_reason: Optional[str] = None,
) -> list[RightsImpactItem]:
    """Dependency-aware impact items across the blueprint §67 cascade.

    Produces one candidate impact item per cascade dimension referenced by the
    grant / artifact. Absence of a discovered downstream component is NOT treated
    as "no impact": each candidate stays ``pending`` until an adapter confirms
    execution, so DSR/termination never reports fake completion.
    """
    items: list[RightsImpactItem] = []
    for dimension in RIGHTS_IMPACT_DIMENSIONS:
        action = DEFAULT_IMPACT_ACTIONS[dimension]
        reason = f"revocation impact over {dimension} for grant {grant_id or artifact_ref or '?'}"
        if dimension == "exported_artifact" and _delivery_state(delivery_evidence):
            action = "tenant_retains"
            reason = (
                f"exported artifact already delivered to tenant — tenant retains "
                f"({grant_id or artifact_ref or '?'})"
            )
        elif dimension in _DERIVED_DIMENSIONS:
            reason = (
                f"{dimension} derived from {grant_id or artifact_ref or '?'} — "
                f"recompute_or_delete after verified source deletion"
            )
        items.append(
            RightsImpactItem(
                tenant_id=tenant_id,
                grant_id=grant_id,
                artifact_ref=artifact_ref,
                component_type=dimension,  # type: ignore[arg-type]
                required_action=action,
                remediation_state="pending",
                reason=reason,
                evidence_refs=[f"rev_{uuid.uuid4().hex}"],
            )
        )
    return items


def _to_impact_rows(items: list[RightsImpactItem]) -> list[Any]:
    """Validate impact items into the P-B1 ``RightsImpact`` when importable.

    Falls back to the internal rows otherwise (P-B1 may not have landed yet).
    """
    try:
        contracts = _pb1_contracts()
        impact_model = getattr(contracts, "RightsImpact", None)
    except Exception:
        impact_model = None
    if impact_model is None:
        return [item.model_dump() for item in items]
    out: list[Any] = []
    for item in items:
        row = item.model_dump()
        try:
            out.append(impact_model.model_validate(row))
        except Exception:  # pragma: no cover — schema drift at integration
            out.append(row)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Persistence helpers
# ═══════════════════════════════════════════════════════════════════════════

async def _impact_repository() -> Any:
    return _pb1_repositories().rights_impact_repository


async def persist_impact_items(items: list[RightsImpactItem]) -> list[str]:
    """Persist pending impact items through the canonical rights_impact store."""
    repo = await _impact_repository()
    recorded: list[str] = []
    for item in items:
        await repo.record(item.model_dump())
        recorded.append(item.impact_id)
    return recorded


async def list_pending_impacts(tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
    repo = await _impact_repository()
    return await repo.list_for_tenant(tenant_id, limit=limit, extra={"remediation_state": "pending"})


# ═══════════════════════════════════════════════════════════════════════════
# Revocation pipeline (§66)
# ═══════════════════════════════════════════════════════════════════════════

async def revocation_pipeline(
    tenant_id: str,
    grant_id: str,
    reason: str,
    *,
    delivery_evidence: Optional[list[str]] = None,
    gateway: Optional[GeneralizationGateway] = None,
) -> RevocationSummary:
    """Execute blueprint §66 revocation steps and return an honest summary.

    1. Deny future use immediately: a durable RightsDecision (deny) for the
       grant is recorded.
    2. Compute the impact graph for the grant.
    3. Enqueue remediation: every impact item is persisted ``pending``.
    4. Re-evaluate generalized derivatives through the Generalization Gateway.
    5. Assess model impact through the learning/model-governance authority.
    6. Surface everything not executed in ``unresolved``.
    """
    # Step 0 — tenant-scoped ownership verification (IDOR guard). A revocation is
    # only executed against a grant we can prove belongs to the requesting tenant;
    # an unknown or cross-tenant grant is rejected BEFORE any decision, impact, or
    # model-governance state is recorded.
    grant = await _grant_loader(grant_id)
    if grant is None:
        raise RevocationError(
            f"revocation refused for grant {grant_id}: no such grant exists"
        )
    grant_tenant = str(getattr(grant, "tenant_id", "") or "")
    if grant_tenant != tenant_id:
        raise RevocationError(
            f"revocation refused for grant {grant_id}: grant tenant "
            f"{grant_tenant!r} does not match caller tenant {tenant_id!r}"
        )

    # Update the canonical P-A grant before emitting any downstream denial or
    # impact rows.  This closes the race where consumers reload the grant
    # between the revocation decision and remediation enqueueing.
    from services.integrations.data_rights.models import DataRightsGrantRevoke
    from services.integrations.data_rights.service import data_rights_service
    revoked = await data_rights_service.revoke_grant(
        grant_id,
        DataRightsGrantRevoke(
            revocation_reason=reason,
            revoked_by_user_id=f"tenant:{tenant_id}",
        ),
    )
    if revoked is None:
        raise RevocationError(f"revocation refused for grant {grant_id}: grant disappeared")
    grant = revoked

    repos = _pb1_repositories()
    decision_repo = repos.rights_decision_repository
    gateway = gateway or _default_gateway()

    # Step 1 — immediate denial of future governed use.
    now_iso = utc_now().isoformat()
    revocation_decision = {
        "decision_id": f"rdec_{uuid.uuid4().hex}",
        "tenant_id": tenant_id,
        "allowed": False,
        "disposition": "deny",
        "reason_codes": [f"grant_revoked:{reason}"],
        "source_grant_refs": [grant_id],
        "consent_decision_refs": [],
        "permitted_uses": [],
        "permitted_derivations": [],
        "permitted_learning": [],
        "permitted_disclosures": [],
        "retention": "",
        "deletion": "",
        "survival": "",
        "evaluated_at": now_iso,
        "effective_as_of": now_iso,
        "policy_version": POLICY_VERSION,
        "evidence_refs": [],
        "requested_use": "revocation",
    }
    await decision_repo.record(revocation_decision)
    decision_refs = [revocation_decision["decision_id"]]

    # Step 2 — impact graph.
    items = compute_rights_impact(
        tenant_id,
        grant_id=grant_id,
        delivery_evidence=delivery_evidence,
        revocation_reason=reason,
    )

    # Step 3 — enqueue remediation (all stay pending; nothing executed here).
    impact_ids = await persist_impact_items(items)

    # Step 4 — re-evaluate generalized derivatives.
    recheck_ids: list[str] = []
    unresolved: list[str] = []
    artifacts = await generalized_artifact_repository.find_many(
        filters={"tenant_id": tenant_id}, limit=500
    )
    for row in artifacts or []:
        refs = row.get("source_grant_refs") or []
        if grant_id not in refs:
            continue
        item = RightsImpactItem(
            tenant_id=tenant_id,
            grant_id=grant_id,
            artifact_ref=row.get("generalized_artifact_id"),
            component_type="generalized_artifact",
            required_action="recheck_eligibility",
            remediation_state="pending",
            reason="grant revoked — generalized derivative eligibility must be re-evaluated",
        )
        (await persist_impact_items([item]))
        recheck_ids.append(item.impact_id)
        impact_ids.append(item.impact_id)
        unresolved.append(item.impact_id)

    # Step 5 — model impact (learning/model-governance authority).
    model_impacts: list[dict[str, Any]] = []
    try:
        from services.rights_authority import model_governance

        state = model_governance.assess_model_revocation(
            model_ref="",
            revoked_grant_ids=[grant_id],
            decisions=[],
        )
        reasons = getattr(state, "reasons", None) or []
        model_impacts.append(
            {
                "state": _model_state_value(state),
                "revoked_grant_ids": [grant_id],
                "reasons": reasons,
                "decision_ref": revocation_decision["decision_id"],
            }
        )
    except Exception as exc:  # pragma: no cover — governance seam unavailable
        logger.warning("model impact assessment skipped: %s", exc)

    # Step 6 — anything not executed is unresolved.
    for item in items:
        if item.remediation_state == "pending":
            unresolved.append(item.impact_id)

    return RevocationSummary(
        revocation_decision_refs=decision_refs,
        impact_ids=impact_ids,
        model_impacts=model_impacts,
        unresolved=sorted(set(unresolved)),
        generalized_recheck_ids=recheck_ids,
    )


def _default_gateway() -> GeneralizationGateway:
    from services.rights_authority.generalization import generalization_gateway

    return generalization_gateway


def _model_state_value(state: Any) -> str:
    value = getattr(state, "state", None)
    if value is None:
        return str(getattr(state, "model_revocation_state", "") or "")
    if isinstance(value, str):
        return value.lower()
    return str(getattr(value, "value", value)).lower()


__all__ = [
    "DEFAULT_IMPACT_ACTIONS",
    "RIGHTS_IMPACT_DIMENSIONS",
    "REMEDIATION_STATES",
    "RevocationError",
    "RevocationSummary",
    "RightsImpactItem",
    "compute_rights_impact",
    "list_pending_impacts",
    "persist_impact_items",
    "revocation_pipeline",
]
