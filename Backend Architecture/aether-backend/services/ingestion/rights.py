"""Rights PEP for the canonical SDK -> Bronze ingestion boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from shared.rights_authority.contracts import (
    ActorRef,
    AttachRightsEnvelope,
    ArtifactRef,
    DestinationRef,
    RightsUseRequest,
)
from shared.rights_authority.pep import RightsPEPResult, evaluate_rights
from shared.rights_authority.pep import rights_mode
from shared.rights_authority.service import RightsAuthority, rights_authority


@dataclass(frozen=True)
class IngestionRightsResult:
    allowed: bool
    reason: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)
    decision_ids: tuple[str, ...] = ()


async def authorize_ingestion(
    tenant_id: str,
    normalized: dict[str, Any],
    *,
    authority: RightsAuthority | None = None,
    source_grant_ref: str | None = None,
    artifact_kind: str = "sdk_event",
) -> IngestionRightsResult:
    """Resolve the server-side grant and policy, then authorize ingest + store.

    A client may supply a hint, but it is only accepted after the durable
    ledger confirms tenant ownership and active status. If no explicit source
    ref is supplied, exactly one active lake grant must exist; ambiguity is a
    safe denial rather than an arbitrary grant selection.
    """
    authority = authority or rights_authority
    if rights_mode() == "off":
        return IngestionRightsResult(allowed=True)

    grants = await authority.repository.list_source_grants(tenant_id)
    latest: dict[str, dict[str, Any]] = {}
    for grant in grants:
        grant_id = grant.get("data_rights_grant_id")
        if not grant_id:
            continue
        if int(grant.get("grant_version", 1)) >= int(latest.get(grant_id, {}).get("grant_version", 0)):
            latest[grant_id] = grant
    candidates = [
        grant for grant in latest.values()
        if grant.get("status") == "active"
        and not grant.get("revoked_at")
        and grant.get("tenant_lake_allowed") is True
    ]
    if source_grant_ref:
        candidates = [grant for grant in candidates if grant.get("data_rights_grant_id") == source_grant_ref]
    if len(candidates) != 1:
        return IngestionRightsResult(
            allowed=False,
            reason="source_grant_missing" if not candidates else "source_grant_ambiguous",
        )
    grant = candidates[0]

    policies = await authority.repository.list_policies(tenant_id)
    active_policies = [
        policy for policy in policies
        if policy.get("activation_state") in {"rights_active", "rights_restricted"}
    ]
    if len(active_policies) != 1:
        return IngestionRightsResult(allowed=False, reason="policy_set_missing_or_ambiguous")
    policy = active_policies[0]
    event_ref = ArtifactRef(kind=artifact_kind, id=str(normalized.get("event_id", "")), tenant_id=tenant_id)
    envelope = await authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref=event_ref,
        primary_rights_class="tenant_contributed_data",
        policy_set_ref=policy["policy_set_id"],
        tenant_id=tenant_id,
        source_grant_refs=[grant["data_rights_grant_id"]],
        consent_snapshot_refs=(
            [str(grant["consent_basis"])] if grant.get("consent_basis") else []
        ),
        source_license_refs=(
            [str(grant["contract_id"] or grant["source_manifest_id"])]
            if grant.get("contract_id") or grant.get("source_manifest_id") else []
        ),
        classification_refs=[str(grant["data_category"])] if grant.get("data_category") else [],
        lineage_root_refs=[event_ref.ref],
        retention_class="tenant_event_90d",
    ))
    actor = ActorRef(kind="service", id="ingestion", tenant_id=tenant_id)
    common = {
        "actor": actor,
        "purpose": "tenant_service",
        "tenant_id": tenant_id,
        "source_grant_refs": [grant["data_rights_grant_id"]],
        "artifacts": [event_ref],
    }
    ingest = await authority.evaluate(RightsUseRequest(action="ingest", **common))
    store = await authority.evaluate(RightsUseRequest(
        action="store",
        envelope_refs=[envelope.envelope_id],
        **common,
    ))
    decisions = (ingest, store)
    denied = next((decision for decision in decisions if decision.outcome not in {"allow", "allow_with_obligations"}), None)
    context = {
        "tenant_id": tenant_id,
        "source_grant_ref": grant["data_rights_grant_id"],
        "policy_set_ref": policy["policy_set_id"],
        "envelope_ref": envelope.envelope_id,
        "lineage_root_ref": event_ref.ref,
        "retention_class": envelope.retention_class,
        "rights_decision_refs": [decision.decision_id for decision in decisions],
        "decision_outcomes": [decision.outcome for decision in decisions],
        "lineage_root_refs": [event_ref.ref],
        "purpose": "tenant_service",
        "obligations": [
            obligation.model_dump(mode="json")
            for decision in decisions
            for obligation in decision.obligations
        ],
        "retention_class": envelope.retention_class,
    }
    if denied is not None:
        return IngestionRightsResult(
            allowed=False,
            reason=f"rights_{denied.outcome}:{','.join(denied.reasons)}",
            context=context,
            decision_ids=tuple(decision.decision_id for decision in decisions),
        )
    return IngestionRightsResult(
        allowed=True,
        context=context,
        decision_ids=tuple(decision.decision_id for decision in decisions),
    )


async def authorize_derivation(
    tenant_id: str,
    *,
    artifact: dict[str, Any],
    input_envelope_refs: list[str],
    policy_set_ref: str | None = None,
    source_grant_refs: Optional[list[str]] = None,
    transform: str = "feature_extraction",
    evidence: Optional[dict[str, Any]] = None,
    authority: RightsAuthority | None = None,
) -> RightsPEPResult:
    """Authorize a Silver/Gold derived write from an existing rights stamp."""
    return await evaluate_rights(
        action="derive",
        tenant_id=tenant_id,
        actor=ActorRef(kind="service", id="lake_derivation", tenant_id=tenant_id),
        purpose="lake_derivation",
        authority=authority,
        artifacts=[artifact],
        envelope_refs=input_envelope_refs,
        policy_set_ref=policy_set_ref,
        source_grant_refs=source_grant_refs or [],
        destination=DestinationRef(kind="tenant", id=tenant_id),
        transform=transform,
        metadata={"transform_evidence": evidence or {}},
    )


def rights_context_from_result(result: RightsPEPResult, *, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Serialize only non-sensitive receipt references into lake rows."""
    context = {
        "rights_decision_refs": [result.decision.decision_id] if result.decision else [],
        "decision_outcomes": [result.decision.outcome] if result.decision else [],
        "policy_set_ref": result.decision.policy_set_ref if result.decision else None,
        "envelope_refs": result.decision.envelope_refs if result.decision else [],
        "evidence_manifest_refs": (
            result.decision.evidence_manifest_refs if result.decision else []
        ),
        "lineage_root_refs": result.decision.lineage_root_refs if result.decision else [],
        "purpose": result.decision.purpose if result.decision else None,
        "obligations": (
            [obligation.model_dump(mode="json") for obligation in result.decision.obligations]
            if result.decision else []
        ),
        "retention_class": next(
            (
                obligation.value for obligation in (result.decision.obligations if result.decision else [])
                if obligation.kind == "ttl" and isinstance(obligation.value, str)
            ),
            None,
        ),
    }
    if extra:
        context.update(extra)
    return context


__all__ = [
    "IngestionRightsResult", "authorize_ingestion", "authorize_derivation",
    "rights_context_from_result", "rights_mode",
]
