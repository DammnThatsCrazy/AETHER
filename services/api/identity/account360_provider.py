"""Account360 product-frame provider over canonical sibling projections.

Account360 is a product surface, not an independent source of truth or a new
technical projection. Its contract binds Profile360, Relationship360, and
Economic360 sections. This provider verifies the requested canonical entity
inside the authenticated tenant, then delegates section mapping, evidence,
freshness, completeness, and slot policy handling to the shared frame
composer. It never reads account/member tables, creates duplicate aggregates,
or writes graph state.

Projection results must already have been produced under their own projection
policy. This class requires an explicit frame disposition and makes every
omitted slot disposition unknown so the shared composer cannot treat missing
policy evaluation as an allow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Sequence

from graph.operational_intelligence.models import EvidenceRef
from shared.intelligence_projections.composition import (
    PRODUCT_360_SURFACE_DEFINITIONS,
    compose_experience360_frame,
)
from shared.intelligence_projections.contracts import (
    Experience360ActorAttribution,
    Experience360Frame,
    Experience360FrameRequest,
    Experience360Freshness,
    Experience360PolicyDisposition,
    Experience360ProjectionProvenance,
    Experience360Quality,
    ProjectionResult,
)
from shared.intelligence_projections.errors import ProjectionError


SURFACE_ID = "account360"
ACCOUNT_IDENTITY_SLOT = "account_identity_and_state"
# The canonical identity model distinguishes ``account`` from ``organization``;
# the latter is the persisted entity-registry kind for a tenant's B2B business
# account. Account360 may represent either account kind, but never a person,
# agent, system actor, or other entity merely because its tenant/id match.
_ACCOUNT_ENTITY_TYPES = frozenset({"account", "organization"})


@dataclass(frozen=True)
class AccountIdentityRead:
    """Outcome of the exact tenant + canonical-entity identity lookup."""

    state: str
    reason_code: Optional[str] = None
    evidence_refs: tuple[EvidenceRef, ...] = ()


class Account360Source(Protocol):
    """Read seam for the canonical entity registry.

    Implementations scope the query by both tenant and exact entity id. The
    provider accepts only a row whose tenant and entity id match the request.
    """

    async def canonical_entity(
        self, tenant_id: str, entity_id: str
    ) -> AccountIdentityRead: ...


class RepositoryAccount360Source:
    """Tenant-filtered adapter over the canonical entities repository."""

    async def canonical_entity(
        self, tenant_id: str, entity_id: str
    ) -> AccountIdentityRead:
        if not tenant_id or not entity_id:
            return AccountIdentityRead("unknown", "account_entity_scope_invalid")
        try:
            from repositories.repos import EntityRepository

            rows = await EntityRepository().find_many(
                filters={"tenant_id": tenant_id, "entity_id": entity_id},
                limit=2,
            )
        except Exception:  # noqa: BLE001 - safe, content-free authority failure
            return AccountIdentityRead(
                "unavailable", "account_entity_authority_unavailable"
            )

        if not isinstance(rows, list):
            return AccountIdentityRead(
                "unknown", "account_entity_authority_invalid_response"
            )
        if len(rows) > 1:
            return AccountIdentityRead("conflicted", "account_entity_identity_ambiguous")
        if not rows:
            return AccountIdentityRead("missing", "account_entity_identity_unresolved")

        row = rows[0]
        if not isinstance(row, dict):
            return AccountIdentityRead(
                "unknown", "account_entity_authority_invalid_response"
            )
        if row.get("tenant_id") != tenant_id or row.get("entity_id") != entity_id:
            return AccountIdentityRead("unknown", "account_entity_scope_mismatch")
        if row.get("entity_type") not in _ACCOUNT_ENTITY_TYPES:
            return AccountIdentityRead("missing", "account_entity_type_mismatch")
        updated_at = row.get("updated_at") or row.get("created_at")
        evidence = EvidenceRef(
            id=entity_id,
            type="entity",
            source="entity_registry",
            observedAt=updated_at if isinstance(updated_at, str) and updated_at else None,
        )
        return AccountIdentityRead("resolved", evidence_refs=(evidence,))


class Account360Provider:
    """Compose the Account360 frame from policy-scoped canonical projections."""

    surface_id = SURFACE_ID
    owns_canonical_truth = False
    graph_mutation_policy = "read_only"

    def __init__(self, source: Optional[Account360Source] = None) -> None:
        self._source = source if source is not None else RepositoryAccount360Source()

    async def compose(
        self,
        request: Experience360FrameRequest,
        projection_results: Sequence[ProjectionResult],
        *,
        frame_policy: Optional[Experience360PolicyDisposition],
        identity_read: Optional[AccountIdentityRead] = None,
        policy_by_slot: Optional[Mapping[str, Experience360PolicyDisposition]] = None,
        freshness_by_slot: Optional[Mapping[str, Experience360Freshness]] = None,
        quality_by_slot: Optional[Mapping[str, Experience360Quality]] = None,
        actor_attribution: Optional[Experience360ActorAttribution] = None,
        actor_attribution_by_slot: Optional[
            Mapping[str, Experience360ActorAttribution]
        ] = None,
        generated_at: Optional[str] = None,
    ) -> Experience360Frame:
        """Build an Account360 frame without relaxing policy or source scope.

        If frame policy is denied, unknown, or redacted, the entity authority
        is not read and all supplied projection results are discarded. Missing
        slot policy is treated as unknown. A request anchored to a historical
        instant is also left unknown because the canonical entity registry has
        no temporal identity replay interface.
        """

        if request.surfaceId != SURFACE_ID:
            raise ProjectionError(
                "Account360 provider received a different product surface",
                context={"surfaceId": request.surfaceId},
            )
        if request.subject.kind != "entity":
            raise ProjectionError(
                "Account360 requires a canonical entity subject",
                context={"surfaceId": request.surfaceId},
            )

        requested_slot_ids = self._requested_slot_ids(request)
        unknown_policy = Experience360PolicyDisposition(
            state="unknown", reasonCodes=["policy_not_evaluated"]
        )
        effective_slot_policy = {
            slot_id: (policy_by_slot or {}).get(slot_id, unknown_policy)
            for slot_id in requested_slot_ids
        }
        effective_frame_policy = frame_policy or unknown_policy

        frame_is_allowed = effective_frame_policy.state in {"allowed", "not_applicable"}
        any_slot_is_allowed = any(
            disposition.state in {"allowed", "not_applicable"}
            for disposition in effective_slot_policy.values()
        )
        if not frame_is_allowed or not any_slot_is_allowed:
            return compose_experience360_frame(
                request,
                [],
                frame_policy=effective_frame_policy,
                policy_by_slot=effective_slot_policy,
                freshness_by_slot=freshness_by_slot,
                quality_by_slot=quality_by_slot,
                actor_attribution=(
                    actor_attribution if frame_is_allowed and any_slot_is_allowed else None
                ),
                actor_attribution_by_slot=(
                    actor_attribution_by_slot
                    if frame_is_allowed and any_slot_is_allowed
                    else None
                ),
                generated_at=generated_at,
            )

        identity = identity_read or await self.resolve_identity(request)

        if identity.state != "resolved":
            return self._unknown_entity_frame(
                request,
                frame_policy=effective_frame_policy,
                policy_by_slot=effective_slot_policy,
                freshness_by_slot=freshness_by_slot,
                quality_by_slot=quality_by_slot,
                generated_at=generated_at,
                reason_code=identity.reason_code or "account_entity_identity_unknown",
            )

        frame = compose_experience360_frame(
            request,
            projection_results,
            frame_policy=effective_frame_policy,
            policy_by_slot=effective_slot_policy,
            freshness_by_slot=freshness_by_slot,
            quality_by_slot=quality_by_slot,
            actor_attribution=actor_attribution,
            actor_attribution_by_slot=actor_attribution_by_slot,
            generated_at=generated_at,
        )
        return self._attach_identity_evidence(
            frame, identity, include_evidence=request.includeEvidence
        )

    async def resolve_identity(
        self, request: Experience360FrameRequest
    ) -> AccountIdentityRead:
        """Check current canonical account identity before sibling reads."""

        if request.surfaceId != SURFACE_ID or request.subject.kind != "entity":
            return AccountIdentityRead("unknown", "account_entity_scope_invalid")
        # Current canonical entity membership cannot establish historical
        # identity. Do not reuse a present-day row for an as-of request.
        if request.asOf is not None:
            return AccountIdentityRead(
                "unknown", "account_entity_temporal_identity_unavailable"
            )
        try:
            return await self._source.canonical_entity(
                request.tenantId, request.subject.id
            )
        except Exception:  # noqa: BLE001 - injected source failure is unknown
            return AccountIdentityRead(
                "unavailable", "account_entity_authority_unavailable"
            )

    @staticmethod
    def _requested_slot_ids(request: Experience360FrameRequest) -> list[str]:
        definition = PRODUCT_360_SURFACE_DEFINITIONS.get(SURFACE_ID)
        slots = definition.get("domainSlots") if isinstance(definition, dict) else None
        if not isinstance(slots, list):
            raise ProjectionError(
                "Account360 surface catalog is unavailable",
                context={"surfaceId": SURFACE_ID},
            )
        catalog_ids = [
            slot["id"]
            for slot in slots
            if isinstance(slot, dict) and isinstance(slot.get("id"), str)
        ]
        if request.requestedSlotIds is not None:
            return list(request.requestedSlotIds)
        return catalog_ids

    @staticmethod
    def _attach_identity_evidence(
        frame: Experience360Frame,
        identity: AccountIdentityRead,
        *,
        include_evidence: bool,
    ) -> Experience360Frame:
        """Attach canonical entity lineage to its slot after shared composition.

        The shared composer remains the policy gate. Identity evidence is added
        only when the identity slot itself is explicitly readable, and no
        sibling slot metadata is changed.
        """

        if not include_evidence or identity.state != "resolved" or not identity.evidence_refs:
            return frame

        slots = list(frame.slots)
        for index, slot in enumerate(slots):
            if (
                slot.id != ACCOUNT_IDENTITY_SLOT
                or slot.policyDisposition.state
                not in {
                    "allowed",
                    "not_applicable",
                }
                or slot.state in {"suppressed", "redacted"}
            ):
                continue

            evidence_refs = _unique_evidence_refs([*slot.evidenceRefs, *identity.evidence_refs])
            identity_provenance = Experience360ProjectionProvenance(
                tenantId=frame.tenantId,
                sourceState="available",
                generatedAt=frame.generatedAt,
                sourceKind="authority",
                claimOrigin="canonical_authority",
                evidenceRefs=list(identity.evidence_refs),
                canonicalAuthorityRefs=["entity_registry"],
            )
            provenance = list(slot.provenance)
            if identity_provenance not in provenance:
                provenance.append(identity_provenance)
            slots[index] = slot.model_copy(
                update={"evidenceRefs": evidence_refs, "provenance": provenance}
            )
            return frame.model_copy(update={"slots": slots})
        return frame

    def _unknown_entity_frame(
        self,
        request: Experience360FrameRequest,
        *,
        frame_policy: Experience360PolicyDisposition,
        policy_by_slot: Mapping[str, Experience360PolicyDisposition],
        freshness_by_slot: Optional[Mapping[str, Experience360Freshness]],
        quality_by_slot: Optional[Mapping[str, Experience360Quality]],
        generated_at: Optional[str],
        reason_code: str,
    ) -> Experience360Frame:
        """Return only missing/unknown slots when the canonical subject is unproven."""

        frame = compose_experience360_frame(
            request,
            [],
            frame_policy=frame_policy,
            policy_by_slot=policy_by_slot,
            freshness_by_slot=freshness_by_slot,
            quality_by_slot=quality_by_slot,
            generated_at=generated_at,
        )
        return frame.model_copy(
            update={"warnings": sorted(set([*frame.warnings, reason_code]))}
        )


def _unique_evidence_refs(refs: Sequence[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[object, ...]] = set()
    unique: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.id, ref.type, ref.source, ref.observedAt, ref.confidence, ref.uri)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique


__all__ = [
    "ACCOUNT_IDENTITY_SLOT",
    "Account360Provider",
    "Account360Source",
    "AccountIdentityRead",
    "RepositoryAccount360Source",
    "SURFACE_ID",
]
