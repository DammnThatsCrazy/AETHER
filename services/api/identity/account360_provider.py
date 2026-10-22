"""Account360 product-frame provider over canonical sibling projections.

Account360 is a product surface, not an independent source of truth or a new
technical projection. Its contract composes governed Profile360,
Relationship360, and Economic360 sections, plus exact membership and risk
authority reads. This provider verifies the requested canonical entity inside
the authenticated tenant, then delegates section mapping, evidence,
freshness, completeness, and slot policy handling to the shared frame
composer. It never reads account/member tables, creates duplicate aggregates,
or writes graph state. The `members`, `agents`, and `profiles` slots read only
tenant-owned `MEMBER_OF` graph facts joined to exact tenant entity-registry
rows; profile frames are separately policy-evaluated and all observed roster
views remain coverage-unknown because the source has no completeness watermark.

Projection results must already have been produced under their own projection
policy. This class requires an explicit frame disposition and makes every
omitted slot disposition unknown so the shared composer cannot treat missing
policy evaluation as an allow.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol, Sequence

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
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionSubject,
    ProjectionResult,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


SURFACE_ID = "account360"
ACCOUNT_IDENTITY_SLOT = "account_summary"
LEGACY_ACCOUNT_IDENTITY_SLOT = "account_identity_and_state"
ACCOUNT_MEMBERS_SLOT = "members"
ACCOUNT_AGENTS_SLOT = "agents"
ACCOUNT_PROFILES_SLOT = "profiles"
ACCOUNT_RISK_SLOT = "risk"
_RISK_CONTEXT_PROJECTION_ID = "risk360"
_MAX_ACCOUNT_MEMBER_EDGES = 10_000
_MAX_ACCOUNT_MEMBER_PROFILE_FRAMES = 100
_MAX_ACCOUNT_MEMBER_PROFILE_CONCURRENCY = 4
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
    entity_type: Optional[str] = None
    display_name: Optional[str] = None
    tenant_id: Optional[str] = None
    entity_id: Optional[str] = None


@dataclass(frozen=True)
class AccountMember:
    """Minimal canonical member identity joined to one exact MEMBER_OF fact."""

    tenant_id: str
    organization_entity_id: str
    entity_id: str
    entity_type: str
    role: Optional[str]
    membership_evidence_ref: EvidenceRef
    entity_evidence_ref: EvidenceRef


@dataclass(frozen=True)
class AccountMembersRead:
    """Current tenant-scoped MEMBER_OF facts with explicit coverage limits."""

    state: str
    tenant_id: str
    organization_entity_id: str
    members: tuple[AccountMember, ...] = ()
    reason_codes: tuple[str, ...] = ()
    source_as_of: Optional[str] = None


@dataclass(frozen=True)
class AccountRiskRead:
    """Exact entity-scoped Risk360 output with explicit limitations."""

    state: str
    result: Optional[ProjectionResult] = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountMemberProfilesRead:
    """Bounded, per-member policy-evaluated Profile360 frames."""

    state: str
    profiles: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    provenance: tuple[Experience360ProjectionProvenance, ...] = ()
    reason_codes: tuple[str, ...] = ()
    source_as_of: Optional[str] = None
    truncated: bool = False


AccountMemberProfileReader = Callable[
    [AccountMember, Experience360FrameRequest], Awaitable[Experience360Frame]
]


class Account360Source(Protocol):
    """Read seam for the canonical entity registry.

    Implementations scope the query by both tenant and exact entity id. The
    provider accepts only a row whose tenant and entity id match the request.
    """

    async def canonical_entity(
        self, tenant_id: str, entity_id: str
    ) -> AccountIdentityRead: ...

    async def account_members(
        self, tenant_id: str, organization_entity_id: str
    ) -> AccountMembersRead: ...


class RepositoryAccount360Source:
    """Tenant-filtered adapter over the canonical entities repository."""

    def __init__(self, graph: Optional[object] = None) -> None:
        self._graph = graph

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
        display_name = row.get("display_name")
        return AccountIdentityRead(
            "resolved",
            evidence_refs=(evidence,),
            entity_type=row["entity_type"],
            display_name=(
                display_name.strip()
                if isinstance(display_name, str) and display_name.strip()
                else None
            ),
            tenant_id=tenant_id,
            entity_id=entity_id,
        )

    async def account_members(
        self, tenant_id: str, organization_entity_id: str
    ) -> AccountMembersRead:
        """Read known organization members from exact tenant MEMBER_OF facts.

        Graph membership is a useful positive source, but there is no source
        watermark proving every account member is represented. The returned
        roster is therefore always degraded when it contains observations and
        unknown when it contains none; absence is never reported as an empty
        member set.
        """

        if not tenant_id or not organization_entity_id:
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_scope_invalid",),
            )

        try:
            from dependencies.providers import get_graph
            from repositories.repos import EntityRepository
            from shared.graph.graph import EdgeType

            graph = self._graph if self._graph is not None else get_graph()
            edges, scan_truncated = await graph.get_edges_for_tenant(
                tenant_id,
                limit=_MAX_ACCOUNT_MEMBER_EDGES,
                edge_types=[EdgeType.MEMBER_OF],
            )
        except Exception:  # noqa: BLE001 - bounded, content-free authority failure
            return AccountMembersRead(
                "unavailable",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_graph_authority_unavailable",),
            )

        if not isinstance(edges, list) or not isinstance(scan_truncated, bool):
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_graph_authority_invalid_response",),
            )

        from shared.graph.graph import tenant_of

        reasons = {"account_member_edge_completeness_unproven"}
        if scan_truncated:
            reasons.add("account_member_tenant_edge_scan_truncated")

        edge_rows: list[tuple[str, Optional[str], EvidenceRef]] = []
        edge_ids: set[str] = set()
        for edge in edges:
            if (
                not hasattr(edge, "properties")
                or not hasattr(edge, "edge_type")
                or not hasattr(edge, "from_vertex_id")
                or not hasattr(edge, "to_vertex_id")
            ):
                reasons.add("account_member_graph_edge_invalid")
                continue
            props = edge.properties if isinstance(edge.properties, dict) else {}
            # The tenant-scoped graph query is the first guard; recheck every
            # returned row and the exact endpoint before treating it as fact.
            if tenant_of(props) != tenant_id:
                reasons.add("account_member_graph_scope_mismatch")
                continue
            if (
                edge.edge_type != EdgeType.MEMBER_OF
                or edge.to_vertex_id != organization_entity_id
            ):
                continue
            member_id = edge.from_vertex_id
            if not isinstance(member_id, str) or not member_id.strip() or member_id == organization_entity_id:
                reasons.add("account_member_graph_endpoint_invalid")
                continue
            membership_state = props.get("membership_state")
            if isinstance(membership_state, str) and membership_state.strip().lower() not in {
                "active",
                "",
            }:
                # Revoked edges are filtered by GraphClient; this handles
                # explicit inactive membership state still present on a row.
                continue
            if props.get("valid_to") not in (None, ""):
                # Current graph edge reads do not evaluate bitemporal validity.
                reasons.add("account_member_edge_valid_time_not_evaluated")
                continue
            idempotency_key = props.get("idempotency_key")
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                reasons.add("account_member_edge_evidence_missing")
                continue
            observed_at = (
                props.get("recorded_at")
                or props.get("valid_from")
                or getattr(edge, "created_at", None)
            )
            evidence = EvidenceRef(
                id=idempotency_key,
                type="relationship",
                source="graph",
                observedAt=(observed_at if isinstance(observed_at, str) else None),
                uri=f"graph://edges/{idempotency_key}",
            )
            role = _safe_member_role(props.get("role"))
            if props.get("role") not in (None, "") and role is None:
                reasons.add("account_member_role_unavailable")
            edge_rows.append((member_id, role, evidence))
            edge_ids.add(member_id)

        if not edge_ids:
            if scan_truncated:
                reasons.add("account_member_edges_not_observed_in_truncated_scan")
            else:
                reasons.add("account_member_edges_not_observed_completeness_unknown")
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=tuple(sorted(reasons)),
            )

        try:
            member_rows, member_rows_truncated = await EntityRepository().find_many_for_tenant_entity_ids(
                tenant_id,
                edge_ids,
            )
        except Exception:  # noqa: BLE001 - bounded, content-free authority failure
            return AccountMembersRead(
                "unavailable",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_entity_authority_unavailable",),
            )
        if not isinstance(member_rows, list) or not isinstance(member_rows_truncated, bool):
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_entity_authority_invalid_response",),
            )
        if member_rows_truncated:
            reasons.add("account_member_entity_rows_ambiguous")

        canonical_by_id: dict[str, dict] = {}
        for row in member_rows:
            if not isinstance(row, dict):
                reasons.add("account_member_entity_row_invalid")
                continue
            member_id = row.get("entity_id")
            if (
                row.get("tenant_id") != tenant_id
                or not isinstance(member_id, str)
                or member_id not in edge_ids
            ):
                reasons.add("account_member_entity_scope_mismatch")
                continue
            if member_id in canonical_by_id:
                reasons.add("account_member_entity_identity_ambiguous")
                canonical_by_id.pop(member_id, None)
                continue
            if row.get("entity_type") not in EntityRepository.VALID_TYPES:
                reasons.add("account_member_entity_type_invalid")
                continue
            canonical_by_id[member_id] = row

        members: list[AccountMember] = []
        seen_members: set[str] = set()
        for member_id, role, membership_ref in edge_rows:
            if member_id in seen_members:
                # Multiple current roles on the same member/account edge have
                # no canonical conflict-resolution rule. Keep no arbitrary one.
                reasons.add("account_member_role_ambiguous")
                members = [member for member in members if member.entity_id != member_id]
                continue
            seen_members.add(member_id)
            row = canonical_by_id.get(member_id)
            if row is None:
                reasons.add("account_member_entity_identity_unresolved")
                continue
            updated_at = row.get("updated_at") or row.get("created_at")
            entity_ref = EvidenceRef(
                id=member_id,
                type="entity",
                source="entity_registry",
                observedAt=(updated_at if isinstance(updated_at, str) else None),
            )
            members.append(
                AccountMember(
                    tenant_id=tenant_id,
                    organization_entity_id=organization_entity_id,
                    entity_id=member_id,
                    entity_type=row["entity_type"],
                    role=role,
                    membership_evidence_ref=membership_ref,
                    entity_evidence_ref=entity_ref,
                )
            )

        if edge_ids - set(canonical_by_id):
            reasons.add("account_member_entity_identity_unresolved")
        if not members:
            reasons.add("account_member_rows_not_resolved")
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=tuple(sorted(reasons)),
            )

        source_as_of_values = [
            ref.observedAt
            for member in members
            for ref in (member.membership_evidence_ref, member.entity_evidence_ref)
            if ref.observedAt
        ]
        return AccountMembersRead(
            "degraded",
            tenant_id,
            organization_entity_id,
            members=tuple(members),
            reason_codes=tuple(sorted(reasons)),
            source_as_of=max(source_as_of_values) if source_as_of_values else None,
        )


class Account360Provider:
    """Compose the Account360 frame from policy-scoped canonical projections."""

    surface_id = SURFACE_ID
    owns_canonical_truth = False
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        source: Optional[Account360Source] = None,
        *,
        risk_provider: Optional[object] = None,
    ) -> None:
        self._source = source if source is not None else RepositoryAccount360Source()
        self._risk_provider = risk_provider

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
        member_profile_reader: Optional[AccountMemberProfileReader] = None,
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
        if request.subject.kind not in {"entity", "account", "workspace"}:
            raise ProjectionError(
                "Account360 received an unsupported subject kind",
                context={"surfaceId": request.surfaceId},
            )

        requested_slot_ids = self._requested_slot_ids(request)
        identity_slot_id = self._identity_slot_id(request, requested_slot_ids)
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

        if request.subject.kind in {"account", "workspace"}:
            # SSOT accepts these subject identifiers, but no canonical
            # account/workspace-to-entity resolver is wired yet. Never assume
            # the identifier is an entity id or reuse an entity projection.
            return self._unknown_entity_frame(
                request,
                frame_policy=effective_frame_policy,
                policy_by_slot=effective_slot_policy,
                freshness_by_slot=freshness_by_slot,
                quality_by_slot=quality_by_slot,
                generated_at=generated_at,
                reason_code=f"account_{request.subject.kind}_identity_resolution_unavailable",
            )

        identity = identity_read or await self.resolve_identity(request)

        if identity.state == "resolved":
            if identity.tenant_id != request.tenantId or identity.entity_id != request.subject.id:
                identity = AccountIdentityRead(
                    "unknown",
                    "account_entity_scope_mismatch",
                    tenant_id=request.tenantId,
                    entity_id=request.subject.id,
                )
            elif identity.entity_type not in _ACCOUNT_ENTITY_TYPES:
                identity = AccountIdentityRead(
                    "missing",
                    "account_entity_type_mismatch",
                    tenant_id=request.tenantId,
                    entity_id=request.subject.id,
                )
            elif not identity.evidence_refs or any(
                ref.id != request.subject.id or ref.source != "entity_registry"
                for ref in identity.evidence_refs
            ):
                identity = AccountIdentityRead(
                    "unknown",
                    "account_entity_identity_evidence_missing_or_unscoped",
                    tenant_id=request.tenantId,
                    entity_id=request.subject.id,
                )

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

        members_read: Optional[AccountMembersRead] = None
        membership_slots = {
            ACCOUNT_MEMBERS_SLOT,
            ACCOUNT_AGENTS_SLOT,
            ACCOUNT_PROFILES_SLOT,
        } & set(requested_slot_ids)
        membership_is_allowed = any(
            effective_slot_policy[slot_id].state in {"allowed", "not_applicable"}
            for slot_id in membership_slots
        )
        if (
            membership_slots
            and request.includeEvidence
            and membership_is_allowed
        ):
            if identity.entity_type == "organization":
                members_read = await self._read_members(request)
            else:
                members_read = AccountMembersRead(
                    "unknown",
                    request.tenantId,
                    request.subject.id,
                    reason_codes=("account_member_graph_subject_kind_unsupported",),
                )

        member_profiles_read: Optional[AccountMemberProfilesRead] = None
        if (
            ACCOUNT_PROFILES_SLOT in requested_slot_ids
            and effective_slot_policy[ACCOUNT_PROFILES_SLOT].state
            in {"allowed", "not_applicable"}
        ):
            if not request.includeEvidence:
                member_profiles_read = AccountMemberProfilesRead(
                    "unknown",
                    reason_codes=("account_member_profiles_evidence_not_requested",),
                )
            elif members_read is None:
                member_profiles_read = AccountMemberProfilesRead(
                    "unknown",
                    reason_codes=("account_member_profile_membership_unavailable",),
                )
            elif identity.entity_type != "organization":
                member_profiles_read = AccountMemberProfilesRead(
                    "unknown",
                    reason_codes=("account_member_profile_organization_subject_required",),
                )
            else:
                member_profiles_read = await self._read_member_profiles(
                    request,
                    members_read,
                    member_profile_reader=member_profile_reader,
                )

        risk_read: Optional[AccountRiskRead] = None
        if ACCOUNT_RISK_SLOT in requested_slot_ids:
            risk_policy = effective_slot_policy[ACCOUNT_RISK_SLOT]
            if risk_policy.state in {"allowed", "not_applicable"}:
                risk_read = await self._read_risk(
                    request,
                    entity_type=identity.entity_type,
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
        frame = self._attach_identity_context(
            frame,
            identity,
            slot_id=identity_slot_id,
            include_evidence=request.includeEvidence,
            freshness_is_explicit=(
                identity_slot_id is not None
                and identity_slot_id in (freshness_by_slot or {})
            ),
        )
        frame = self._attach_members_context(
            frame,
            members_read,
            include_evidence=request.includeEvidence,
            requested_slot_ids=requested_slot_ids,
        )
        frame = self._attach_member_profiles_context(
            frame,
            member_profiles_read,
            include_evidence=request.includeEvidence,
            requested_slot_ids=requested_slot_ids,
        )
        return self._attach_risk_context(
            frame,
            risk_read,
            include_evidence=request.includeEvidence,
            requested_slot_ids=requested_slot_ids,
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
            identity = await self._source.canonical_entity(
                request.tenantId, request.subject.id
            )
        except Exception:  # noqa: BLE001 - injected source failure is unknown
            return AccountIdentityRead(
                "unavailable",
                "account_entity_authority_unavailable",
                tenant_id=request.tenantId,
                entity_id=request.subject.id,
            )
        if not isinstance(identity, AccountIdentityRead):
            return AccountIdentityRead(
                "unknown",
                "account_entity_authority_invalid_response",
                tenant_id=request.tenantId,
                entity_id=request.subject.id,
            )
        if identity.tenant_id is None and identity.entity_id is None:
            return AccountIdentityRead(
                state=identity.state,
                reason_code=identity.reason_code,
                evidence_refs=identity.evidence_refs,
                entity_type=identity.entity_type,
                display_name=identity.display_name,
                tenant_id=request.tenantId,
                entity_id=request.subject.id,
            )
        if identity.tenant_id != request.tenantId or identity.entity_id != request.subject.id:
            return AccountIdentityRead(
                "unknown",
                "account_entity_scope_mismatch",
                tenant_id=request.tenantId,
                entity_id=request.subject.id,
            )
        return identity

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
    def _identity_slot_id(
        request: Experience360FrameRequest, requested_slot_ids: Sequence[str]
    ) -> Optional[str]:
        """Return the exact SSOT summary slot, with a temporary legacy fallback."""

        catalog_ids = set(Account360Provider._requested_slot_ids(request))
        requested = set(requested_slot_ids)
        for slot_id in (ACCOUNT_IDENTITY_SLOT, LEGACY_ACCOUNT_IDENTITY_SLOT):
            if slot_id in catalog_ids and slot_id in requested:
                return slot_id
        return None

    async def _read_members(
        self, request: Experience360FrameRequest
    ) -> AccountMembersRead:
        """Read exact membership dependencies for policy-allowed account slots.

        When ``profiles`` is requested, its own Account360 slot policy gates
        this lookup. Each returned member is then evaluated again under the
        Profile360 policy before any Profile360 provider reads are performed.
        """

        reader = getattr(self._source, "account_members", None)
        if not callable(reader):
            return AccountMembersRead(
                "unknown",
                request.tenantId,
                request.subject.id,
                reason_codes=("account_member_authority_not_configured",),
            )
        try:
            result = await reader(request.tenantId, request.subject.id)
        except Exception:  # noqa: BLE001 - direct source seam fails closed
            return AccountMembersRead(
                "unavailable",
                request.tenantId,
                request.subject.id,
                reason_codes=("account_member_authority_unavailable",),
            )
        if not isinstance(result, AccountMembersRead):
            return AccountMembersRead(
                "unknown",
                request.tenantId,
                request.subject.id,
                reason_codes=("account_member_authority_invalid_response",),
            )
        if (
            result.tenant_id != request.tenantId
            or result.organization_entity_id != request.subject.id
        ):
            return AccountMembersRead(
                "unknown",
                request.tenantId,
                request.subject.id,
                reason_codes=("account_member_scope_mismatch",),
            )
        if result.state not in {"degraded", "unknown", "unavailable", "conflicted", "truncated"}:
            return AccountMembersRead(
                "unknown",
                request.tenantId,
                request.subject.id,
                reason_codes=("account_member_authority_invalid_state",),
            )

        allowed_types = {"human", "agent", "organization", "system"}
        validated_members: list[AccountMember] = []
        seen_member_ids: set[str] = set()
        for member in result.members:
            if (
                not isinstance(member, AccountMember)
                or member.tenant_id != request.tenantId
                or member.organization_entity_id != request.subject.id
                or not isinstance(member.entity_id, str)
                or not member.entity_id.strip()
                or member.entity_id == request.subject.id
                or member.entity_type not in allowed_types
                or member.entity_id in seen_member_ids
                or not isinstance(member.membership_evidence_ref, EvidenceRef)
                or member.membership_evidence_ref.type != "relationship"
                or member.membership_evidence_ref.source != "graph"
                or not member.membership_evidence_ref.id.strip()
                or not isinstance(member.entity_evidence_ref, EvidenceRef)
                or member.entity_evidence_ref.type != "entity"
                or member.entity_evidence_ref.source != "entity_registry"
                or member.entity_evidence_ref.id != member.entity_id
            ):
                return AccountMembersRead(
                    "unknown",
                    request.tenantId,
                    request.subject.id,
                    reason_codes=("account_member_authority_scope_or_evidence_invalid",),
                )
            role = _safe_member_role(member.role)
            if member.role is not None and role is None:
                return AccountMembersRead(
                    "unknown",
                    request.tenantId,
                    request.subject.id,
                    reason_codes=("account_member_role_invalid",),
                )
            seen_member_ids.add(member.entity_id)
            validated_members.append(member)

        reasons = tuple(
            reason
            for reason in result.reason_codes
            if isinstance(reason, str)
            and reason
            and len(reason) <= 96
            and reason.isascii()
            and all(char.isalnum() or char in {"_", "-"} for char in reason)
        )
        return AccountMembersRead(
            result.state,
            request.tenantId,
            request.subject.id,
            members=tuple(validated_members),
            reason_codes=reasons,
            source_as_of=(result.source_as_of if isinstance(result.source_as_of, str) else None),
        )

    @staticmethod
    async def _read_member_profiles(
        request: Experience360FrameRequest,
        members_read: AccountMembersRead,
        *,
        member_profile_reader: Optional[AccountMemberProfileReader],
    ) -> AccountMemberProfilesRead:
        """Compose bounded exact-member Profile360 frames under member policy.

        Account membership facts identify candidate subjects only. The injected
        reader must evaluate the separate Profile360 policy for each exact
        member before resolving any profile projection. No profile is read
        when that reader is unavailable.
        """

        if member_profile_reader is None:
            return AccountMemberProfilesRead(
                "unknown",
                reason_codes=("account_member_profile_reader_unavailable",),
                source_as_of=members_read.source_as_of,
            )
        if members_read.state not in {"degraded", "truncated"}:
            return AccountMemberProfilesRead(
                members_read.state
                if members_read.state in {"unavailable", "conflicted", "truncated"}
                else "unknown",
                reason_codes=(
                    *members_read.reason_codes,
                    "account_member_profile_membership_scope_not_usable",
                ),
                source_as_of=members_read.source_as_of,
            )
        if not members_read.members:
            return AccountMemberProfilesRead(
                "unknown",
                reason_codes=(
                    *members_read.reason_codes,
                    "account_member_profile_roster_completeness_unknown",
                ),
                source_as_of=members_read.source_as_of,
            )

        ordered_members = sorted(members_read.members, key=lambda item: item.entity_id)
        selected_members = ordered_members[:_MAX_ACCOUNT_MEMBER_PROFILE_FRAMES]
        fanout_truncated = len(ordered_members) > len(selected_members)
        semaphore = asyncio.Semaphore(_MAX_ACCOUNT_MEMBER_PROFILE_CONCURRENCY)

        async def read_one(
            member: AccountMember,
        ) -> tuple[Optional[Experience360Frame], Optional[str]]:
            async with semaphore:
                try:
                    profile_frame = await member_profile_reader(member, request)
                except Exception:  # noqa: BLE001 - member policy/provider failures are opaque
                    return None, "account_member_profile_read_unavailable"
            expected_subject_kind = "agent" if member.entity_type == "agent" else "entity"
            if (
                not isinstance(profile_frame, Experience360Frame)
                or profile_frame.surfaceId != "profile360"
                or profile_frame.tenantId != request.tenantId
                or profile_frame.subject.kind != expected_subject_kind
                or profile_frame.subject.id != member.entity_id
                or profile_frame.contractVersion
                != INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
            ):
                return None, "account_member_profile_frame_scope_or_contract_invalid"
            visible_profile_slots = [
                slot
                for slot in profile_frame.slots
                if slot.policyDisposition.state in {"allowed", "not_applicable"}
            ]
            if not visible_profile_slots:
                return None, "account_member_profile_policy_withheld_or_unknown"
            return profile_frame, None

        results = await asyncio.gather(*(read_one(member) for member in selected_members))
        profile_entries: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        provenance: list[Experience360ProjectionProvenance] = []
        reasons = set(members_read.reason_codes)
        reasons.add("account_member_profile_roster_completeness_unknown")
        if fanout_truncated:
            reasons.add("account_member_profile_fanout_truncated")

        for member, (profile_frame, reason) in zip(selected_members, results, strict=True):
            if profile_frame is None:
                if reason:
                    reasons.add(reason)
                continue
            membership_refs = _unique_evidence_refs(
                [member.membership_evidence_ref, member.entity_evidence_ref]
            )
            visible_profile_slots = [
                slot
                for slot in profile_frame.slots
                if slot.policyDisposition.state in {"allowed", "not_applicable"}
            ]
            profile_refs = _unique_evidence_refs(
                [
                    ref
                    for slot in visible_profile_slots
                    for ref in [
                        *slot.evidenceRefs,
                        *(item for line in slot.provenance for item in line.evidenceRefs),
                    ]
                ]
            )
            combined_refs = _unique_evidence_refs([*membership_refs, *profile_refs])
            evidence_refs.extend(combined_refs)
            provenance.extend(
                line
                for slot in visible_profile_slots
                for line in slot.provenance
            )
            provenance.append(
                Experience360ProjectionProvenance(
                    tenantId=request.tenantId,
                    sourceState="degraded",
                    generatedAt=profile_frame.generatedAt,
                    sourceKind="authority",
                    claimOrigin="canonical_authority",
                    evidenceRefs=membership_refs,
                    canonicalAuthorityRefs=["graph", "entity_registry"],
                )
            )
            profile_entries.append(
                {
                    "member": {
                        "kind": profile_frame.subject.kind,
                        "id": member.entity_id,
                        "entityType": member.entity_type,
                    },
                    "membershipEvidenceRefIds": [ref.id for ref in membership_refs],
                    "profileFrame": profile_frame.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                }
            )

        if not profile_entries:
            return AccountMemberProfilesRead(
                "unknown",
                reason_codes=tuple(sorted(reasons)),
                source_as_of=members_read.source_as_of,
                truncated=fanout_truncated,
            )
        return AccountMemberProfilesRead(
            "degraded",
            profiles=tuple(profile_entries),
            evidence_refs=tuple(_unique_evidence_refs(evidence_refs)),
            provenance=tuple(_unique_provenance(provenance)),
            reason_codes=tuple(sorted(reasons)),
            source_as_of=members_read.source_as_of,
            truncated=fanout_truncated,
        )

    async def _read_risk(
        self,
        request: Experience360FrameRequest,
        *,
        entity_type: Optional[str],
    ) -> AccountRiskRead:
        """Reuse Risk360's canonical entity read under Account's risk policy.

        This path is intentionally limited to an exact, already-resolved
        Account entity. It does not treat account_id as entity_id, aggregate
        member risk, or imply coverage for related entities. The owning
        Risk360 provider retains risk record validation and claim semantics.
        """

        if request.subject.kind != "entity" or entity_type not in _ACCOUNT_ENTITY_TYPES:
            return AccountRiskRead(
                "unknown",
                reason_codes=("account_risk_entity_subject_unavailable",),
            )
        if request.asOf is not None or request.timeRange is not None:
            return AccountRiskRead(
                "unknown",
                reason_codes=("account_risk_temporal_projection_unavailable",),
            )
        if not request.includeEvidence:
            return AccountRiskRead(
                "unknown",
                reason_codes=("account_risk_evidence_not_requested",),
            )

        provider = self._risk_provider
        if provider is None:
            try:
                from intelligence.risk360.provider import Risk360Provider

                provider = Risk360Provider()
                self._risk_provider = provider
            except Exception:  # noqa: BLE001 - optional authority fails closed
                return AccountRiskRead(
                    "unavailable",
                    reason_codes=("account_risk_provider_unavailable",),
                )

        projection_request = ProjectionRequest(
            projectionId=_RISK_CONTEXT_PROJECTION_ID,
            tenantId=request.tenantId,
            subject=ProjectionSubject(kind="entity", id=request.subject.id),
            includeSections=["summary", "state", "evidence"],
            includeClaims=True,
            temporalMode="window",
        )
        # Risk360's profile/cluster enrichments are not joined by Account360.
        # Preserve the canonical provider's own degraded summary/state output
        # instead of declaring those dependencies available from unrelated
        # Account slots.
        projection_context = ProjectionContext(
            projectionId=_RISK_CONTEXT_PROJECTION_ID,
            tenantId=request.tenantId,
            registryState="implemented",
            dependencyState=[
                ProjectionDependencyState(
                    projectionId="profile360",
                    state="unknown",
                    reason="account_risk_profile_context_not_joined",
                ),
                ProjectionDependencyState(
                    projectionId="cluster360",
                    state="unknown",
                    reason="account_risk_cluster_context_not_joined",
                ),
            ],
            warnings=["account_risk_related_entity_join_not_available"],
        )
        project = getattr(provider, "project", None)
        if not callable(project):
            return AccountRiskRead(
                "unavailable",
                reason_codes=("account_risk_provider_invalid",),
            )
        try:
            result = await project(projection_request, projection_context)
        except Exception:  # noqa: BLE001 - direct provider failure remains opaque
            return AccountRiskRead(
                "unavailable",
                reason_codes=("account_risk_provider_unavailable",),
            )
        if not isinstance(result, ProjectionResult):
            return AccountRiskRead(
                "unknown",
                reason_codes=("account_risk_provider_invalid_response",),
            )
        return AccountRiskRead("degraded", result=result)

    @staticmethod
    def _attach_members_context(
        frame: Experience360Frame,
        members_read: Optional[AccountMembersRead],
        *,
        include_evidence: bool,
        requested_slot_ids: Sequence[str],
    ) -> Experience360Frame:
        """Attach only evidenced, policy-permitted membership facts.

        The graph source has no completeness watermark, so observed members
        and agent members always render as degraded. A successful empty edge
        read stays unknown. Agent identities are included in ``members`` only
        when the independently gated ``agents`` slot is requested and allowed.
        """

        if not include_evidence:
            reason = "account_membership_evidence_not_requested"
            slots = list(frame.slots)
            for index, slot in enumerate(slots):
                if (
                    slot.id not in requested_slot_ids
                    or slot.id not in {ACCOUNT_MEMBERS_SLOT, ACCOUNT_AGENTS_SLOT}
                    or slot.policyDisposition.state not in {"allowed", "not_applicable"}
                ):
                    continue
                slots[index] = slot.model_copy(
                    update={
                        "state": "unknown",
                        "content": None,
                        "claims": [],
                        "provenance": [],
                        "evidenceRefs": [],
                        "freshness": Experience360Freshness(state="unknown"),
                        "quality": Experience360Quality(
                            state="unknown", reasonCodes=[reason]
                        ),
                        "limitations": sorted(set([*slot.limitations, reason])),
                        "reasonCodes": sorted(set([*slot.reasonCodes, reason])),
                    }
                )
            return frame.model_copy(update={"slots": slots})
        if members_read is None:
            return frame
        requested = set(requested_slot_ids)
        slots = list(frame.slots)
        agents_slot_allowed = ACCOUNT_AGENTS_SLOT in requested and any(
            slot.id == ACCOUNT_AGENTS_SLOT
            and slot.policyDisposition.state in {"allowed", "not_applicable"}
            for slot in slots
        )
        members_for_slot = tuple(
            member
            for member in members_read.members
            if member.entity_type != "agent" or agents_slot_allowed
        )
        agents_for_slot = tuple(
            member
            for member in members_read.members
            if member.entity_type == "agent"
        )

        slot_members = {
            ACCOUNT_MEMBERS_SLOT: (
                members_for_slot,
                "members",
                "account_member_edge_completeness_unproven",
                "account_member_edges_not_observed_completeness_unknown",
            ),
            ACCOUNT_AGENTS_SLOT: (
                agents_for_slot,
                "agents",
                "account_agent_member_edge_completeness_unproven",
                "account_agent_membership_not_observed_completeness_unknown",
            ),
        }
        for index, slot in enumerate(slots):
            if slot.id not in requested or slot.id not in slot_members:
                continue
            if slot.policyDisposition.state not in {"allowed", "not_applicable"}:
                continue

            slot_members_found, output_key, coverage_reason, empty_reason = slot_members[
                slot.id
            ]
            evidence_refs = _unique_evidence_refs(
                [
                    ref
                    for member in slot_members_found
                    for ref in (
                        member.membership_evidence_ref,
                        member.entity_evidence_ref,
                    )
                ]
            )
            reasons = set(members_read.reason_codes)
            if slot_members_found:
                reasons.add(coverage_reason)
            else:
                reasons.add(empty_reason)

            if not slot_members_found or not evidence_refs:
                # Keep any sibling projection out of a direct slot when its
                # exact membership facts could not be verified.
                if slot.content is not None:
                    continue
                state = (
                    members_read.state
                    if members_read.state in {"unavailable", "conflicted", "truncated"}
                    else "unknown"
                )
                slots[index] = slot.model_copy(
                    update={
                        "state": state,
                        "content": None,
                        "freshness": Experience360Freshness(
                            state="unknown",
                            sourceAsOf=members_read.source_as_of,
                        ),
                        "limitations": sorted(set([*slot.limitations, *reasons])),
                        "reasonCodes": sorted(set([*slot.reasonCodes, *reasons])),
                    }
                )
                continue

            membership_provenance = Experience360ProjectionProvenance(
                tenantId=frame.tenantId,
                sourceState="degraded",
                generatedAt=frame.generatedAt,
                sourceKind="authority",
                claimOrigin="canonical_authority",
                evidenceRefs=evidence_refs,
                canonicalAuthorityRefs=["graph", "entity_registry"],
            )
            content = {
                "subject": {"kind": "entity", "id": frame.subject.id},
                "membershipRelation": "MEMBER_OF",
                output_key: [
                    {
                        "entity": {
                            "kind": "entity",
                            "id": member.entity_id,
                            "entityType": member.entity_type,
                        },
                        "role": member.role,
                        "evidenceRefIds": [
                            member.membership_evidence_ref.id,
                            member.entity_evidence_ref.id,
                        ],
                    }
                    for member in slot_members_found
                ],
                "coverage": {"state": "unknown", "reason": coverage_reason},
            }
            provenance = list(slot.provenance)
            if membership_provenance not in provenance:
                provenance.append(membership_provenance)
            slots[index] = slot.model_copy(
                update={
                    "state": "degraded",
                    "content": content,
                    "evidenceRefs": evidence_refs,
                    "provenance": provenance,
                    "freshness": Experience360Freshness(
                        state="unknown",
                        sourceAsOf=members_read.source_as_of,
                    ),
                    "quality": Experience360Quality(
                        state="partial",
                        evidenceRefs=evidence_refs,
                        reasonCodes=sorted(reasons),
                    ),
                    "limitations": sorted(
                        set(
                            [
                                *slot.limitations,
                                *reasons,
                                "account_member_freshness_sla_unconfigured",
                            ]
                        )
                    ),
                    "reasonCodes": sorted(set([*slot.reasonCodes, *reasons])),
                }
            )
        return frame.model_copy(update={"slots": slots})

    @staticmethod
    def _attach_member_profiles_context(
        frame: Experience360Frame,
        profiles_read: Optional[AccountMemberProfilesRead],
        *,
        include_evidence: bool,
        requested_slot_ids: Sequence[str],
    ) -> Experience360Frame:
        """Attach only per-member Profile360 frames that passed their own policy."""

        if ACCOUNT_PROFILES_SLOT not in requested_slot_ids:
            return frame
        slots = list(frame.slots)
        profile_index = next(
            (index for index, slot in enumerate(slots) if slot.id == ACCOUNT_PROFILES_SLOT),
            None,
        )
        if profile_index is None:
            return frame
        slot = slots[profile_index]
        if slot.policyDisposition.state not in {"allowed", "not_applicable"}:
            return frame

        reasons = set(profiles_read.reason_codes if profiles_read is not None else ())
        if not include_evidence:
            reasons.add("account_member_profiles_evidence_not_requested")
        if profiles_read is None:
            reasons.add("account_member_profile_read_not_requested")
        if (
            not include_evidence
            or profiles_read is None
            or profiles_read.state != "degraded"
            or not profiles_read.profiles
            or not profiles_read.evidence_refs
            or not profiles_read.provenance
        ):
            state = (
                profiles_read.state
                if profiles_read is not None
                and profiles_read.state in {"unavailable", "conflicted", "truncated"}
                else "unknown"
            )
            slots[profile_index] = slot.model_copy(
                update={
                    "state": state,
                    "content": None,
                    "claims": [],
                    "provenance": [],
                    "evidenceRefs": [],
                    "freshness": Experience360Freshness(
                        state="unknown",
                        sourceAsOf=(profiles_read.source_as_of if profiles_read else None),
                    ),
                    "quality": Experience360Quality(
                        state="unknown", reasonCodes=sorted(reasons)
                    ),
                    "limitations": sorted(set([*slot.limitations, *reasons])),
                    "reasonCodes": sorted(set([*slot.reasonCodes, *reasons])),
                }
            )
            return frame.model_copy(update={"slots": slots})

        evidence_refs = _unique_evidence_refs(
            [*slot.evidenceRefs, *profiles_read.evidence_refs]
        )
        provenance = list(slot.provenance)
        for item in profiles_read.provenance:
            if item not in provenance:
                provenance.append(item)
        reasons.update(
            {
                "account_member_profile_roster_completeness_unknown",
                "account_member_profiles_freshness_sla_unconfigured",
            }
        )
        content = {
            "subject": {"kind": frame.subject.kind, "id": frame.subject.id},
            "membershipRelation": "MEMBER_OF",
            "profiles": list(profiles_read.profiles),
            "coverage": {
                "state": "partial",
                "profilesReturned": len(profiles_read.profiles),
                "reason": "account_member_profile_roster_completeness_unknown",
            },
        }
        slots[profile_index] = slot.model_copy(
            update={
                "state": "degraded",
                "content": content,
                "claims": [],
                "provenance": provenance,
                "evidenceRefs": evidence_refs,
                "freshness": Experience360Freshness(
                    state="unknown",
                    sourceAsOf=profiles_read.source_as_of,
                ),
                "quality": Experience360Quality(
                    state="partial",
                    evidenceRefs=evidence_refs,
                    reasonCodes=sorted(reasons),
                ),
                "limitations": sorted(set([*slot.limitations, *reasons])),
                "reasonCodes": sorted(set([*slot.reasonCodes, *reasons])),
            }
        )
        return frame.model_copy(update={"slots": slots})

    @staticmethod
    def _attach_risk_context(
        frame: Experience360Frame,
        risk_read: Optional[AccountRiskRead],
        *,
        include_evidence: bool,
        requested_slot_ids: Sequence[str],
    ) -> Experience360Frame:
        """Attach only exact, evidence-backed direct-entity risk context."""

        if ACCOUNT_RISK_SLOT not in requested_slot_ids:
            return frame
        slots = list(frame.slots)
        risk_index = next(
            (index for index, slot in enumerate(slots) if slot.id == ACCOUNT_RISK_SLOT),
            None,
        )
        if risk_index is None:
            return frame
        slot = slots[risk_index]
        if slot.policyDisposition.state not in {"allowed", "not_applicable"}:
            return frame

        base_reasons = set(risk_read.reason_codes if risk_read is not None else ())
        if not include_evidence:
            base_reasons.add("account_risk_evidence_not_requested")
        if risk_read is None:
            base_reasons.add("account_risk_projection_not_requested")

        result = risk_read.result if risk_read is not None else None
        if result is not None:
            if (
                result.projectionId != _RISK_CONTEXT_PROJECTION_ID
                or result.tenantId != frame.tenantId
                or result.contractVersion
                != INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
                or any(claim.subject != frame.subject for claim in result.claims)
            ):
                result = None
                base_reasons.add("account_risk_projection_scope_or_contract_invalid")

        sections_by_id: dict[str, Any] = {}
        if result is not None:
            for section in result.sections:
                if section.id in sections_by_id:
                    base_reasons.add("account_risk_projection_section_ambiguous")
                    sections_by_id.clear()
                    result = None
                    break
                sections_by_id[section.id] = section

        summary = sections_by_id.get("summary") if result is not None else None
        state = sections_by_id.get("state") if result is not None else None
        for section in (summary, state):
            if section is None:
                base_reasons.add("account_risk_projection_section_unavailable")
                continue
            content = section.content
            if (
                not isinstance(content, Mapping)
                or content.get("tenantId") != frame.tenantId
                or content.get("subject")
                != {"kind": frame.subject.kind, "id": frame.subject.id}
            ):
                base_reasons.add("account_risk_projection_subject_mismatch")
                result = None
                break
            if section.state not in {"available", "degraded", "empty", "missing"}:
                base_reasons.add("account_risk_projection_section_state_unsupported")
                result = None
                break
            if section.warnings:
                base_reasons.add("account_risk_source_section_degraded")

        risk_claims = []
        evidence_refs: list[EvidenceRef] = []
        if result is not None and include_evidence:
            risk_claims = [
                claim.model_copy(update={"domainSlotIds": [ACCOUNT_RISK_SLOT]})
                for claim in result.claims
                if claim.subject == frame.subject
                and set(claim.domainSlotIds or [])
                & {"risk_summary", "risk_assessment_state", "risk_evidence_and_limitations", "evidence_trace"}
                and claim.evidenceRefs
            ]
            evidence_refs = _unique_evidence_refs(
                [ref for claim in risk_claims for ref in claim.evidenceRefs]
            )

        # Never turn an absent assessment or an evidence-free payload into a
        # positive/empty account-risk assertion. The Risk360 source's exact
        # entity observations are required before content can be attached.
        if (
            result is None
            or summary is None
            or state is None
            or summary.state == "missing"
            or not risk_claims
            or not evidence_refs
        ):
            if result is not None and summary is not None and summary.state == "missing":
                base_reasons.add("account_risk_assessment_not_observed")
            if result is not None and not evidence_refs:
                base_reasons.add("account_risk_evidence_missing")
            state_name = (
                risk_read.state
                if risk_read is not None
                and risk_read.state in {"unavailable", "conflicted", "truncated"}
                else "unknown"
            )
            slots[risk_index] = slot.model_copy(
                update={
                    "state": state_name,
                    "content": None,
                    "claims": [],
                    "provenance": [],
                    "evidenceRefs": [],
                    "freshness": Experience360Freshness(state="unknown"),
                    "quality": Experience360Quality(
                        state="unknown", reasonCodes=sorted(base_reasons)
                    ),
                    "limitations": sorted(set([*slot.limitations, *base_reasons])),
                    "reasonCodes": sorted(set([*slot.reasonCodes, *base_reasons])),
                }
            )
            return frame.model_copy(update={"slots": slots})

        partial_reasons = {
            "account_risk_related_entity_join_not_available",
            "account_risk_freshness_sla_unconfigured",
            "account_risk_profile_context_not_joined",
            "account_risk_cluster_context_not_joined",
        }
        reasons = base_reasons | partial_reasons
        provenance: list[Experience360ProjectionProvenance] = []
        for section in (summary, state):
            provenance.append(
                Experience360ProjectionProvenance(
                    tenantId=frame.tenantId,
                    projectionId=_RISK_CONTEXT_PROJECTION_ID,
                    sourceKind="section",
                    sectionId=section.id,
                    sourceState=section.state,
                    generatedAt=result.generatedAt,
                    claimOrigin="unknown",
                    evidenceRefs=evidence_refs,
                    canonicalAuthorityRefs=["risk_outputs"],
                )
            )
        content = {
            "subject": {"kind": frame.subject.kind, "id": frame.subject.id},
            "scope": "direct_account_entity_only",
            "summary": dict(summary.content),
            "state": dict(state.content),
            "coverage": {
                "state": "partial",
                "reason": "account_risk_related_entity_join_not_available",
            },
        }
        slots[risk_index] = slot.model_copy(
            update={
                "state": "degraded",
                "content": content,
                "claims": risk_claims,
                "provenance": provenance,
                "evidenceRefs": evidence_refs,
                "freshness": Experience360Freshness(
                    state="unknown",
                ),
                "quality": Experience360Quality(
                    state="partial",
                    evidenceRefs=evidence_refs,
                    reasonCodes=sorted(reasons),
                ),
                "limitations": sorted(set([*slot.limitations, *reasons])),
                "reasonCodes": sorted(set([*slot.reasonCodes, *reasons])),
            }
        )
        return frame.model_copy(update={"slots": slots})

    @staticmethod
    def _attach_identity_context(
        frame: Experience360Frame,
        identity: AccountIdentityRead,
        *,
        slot_id: Optional[str],
        include_evidence: bool,
        freshness_is_explicit: bool,
    ) -> Experience360Frame:
        """Attach canonical entity identity and lineage after shared composition.

        The shared composer remains the policy gate. Identity evidence is added
        only when the identity slot itself is explicitly readable. The entity
        registry has no account lifecycle field, so this adds a partial account
        identity view and marks lifecycle state and unevaluated freshness
        explicitly unknown instead of inferring them from profile data.
        """

        if (
            slot_id is None
            or not include_evidence
            or identity.state != "resolved"
            or not identity.evidence_refs
        ):
            return frame

        slots = list(frame.slots)
        for index, slot in enumerate(slots):
            if (
                slot.id != slot_id
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

            reasons = set(slot.reasonCodes)
            limitations = set(slot.limitations)
            content = slot.content
            state = slot.state
            has_account_identity_context = False

            if identity.entity_type in _ACCOUNT_ENTITY_TYPES:
                lifecycle_reason = "account_lifecycle_state_not_exposed_by_entity_registry"
                canonical_identity = {
                    "kind": "entity",
                    "id": frame.subject.id,
                    "entityType": identity.entity_type,
                    "identityState": "resolved",
                }
                if isinstance(identity.display_name, str) and identity.display_name.strip():
                    canonical_identity["displayName"] = identity.display_name.strip()
                account_state = {"state": "unknown", "reason": lifecycle_reason}

                if isinstance(content, Mapping):
                    content = dict(content)
                    has_account_identity_context = True
                elif content is None and slot.state in {
                    "missing",
                    "unknown",
                    "unavailable",
                    "degraded",
                }:
                    content = {"sections": [], "claims": []}
                    has_account_identity_context = True
                    reasons.add("profile360_account_identity_state_unavailable")
                    limitations.add("profile360_account_identity_state_unavailable")
                    state = "degraded"
                else:
                    # Preserve provider output if its shape is not the shared
                    # composer contract; never replace it with a guessed shape.
                    has_account_identity_context = False

                if isinstance(content, dict):
                    content["canonicalEntity"] = canonical_identity
                    content["accountState"] = account_state
                    reasons.add(lifecycle_reason)
                    limitations.add(lifecycle_reason)
                    if state == "available":
                        state = "degraded"

            freshness = slot.freshness
            if not freshness_is_explicit and has_account_identity_context:
                source_as_of = next(
                    (ref.observedAt for ref in identity.evidence_refs if ref.observedAt),
                    None,
                )
                freshness = Experience360Freshness(
                    state="unknown",
                    sourceAsOf=source_as_of,
                )

            slots[index] = slot.model_copy(
                update={
                    "state": state,
                    "content": content,
                    "evidenceRefs": evidence_refs,
                    "provenance": provenance,
                    "freshness": freshness,
                    "limitations": sorted(limitations),
                    "reasonCodes": sorted(reasons),
                }
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
        """Return a content-free unknown frame when the canonical subject is unproven."""

        frame = compose_experience360_frame(
            request,
            [],
            frame_policy=frame_policy,
            policy_by_slot=policy_by_slot,
            freshness_by_slot=freshness_by_slot,
            quality_by_slot=quality_by_slot,
            generated_at=generated_at,
        )
        unknown_slots = []
        for slot in frame.slots:
            if slot.policyDisposition.state in {"denied", "redacted"}:
                unknown_slots.append(slot)
                continue
            unknown_slots.append(
                slot.model_copy(
                    update={
                        "state": "unknown",
                        "content": None,
                        "claims": [],
                        "provenance": [],
                        "evidenceRefs": [],
                        "freshness": Experience360Freshness(state="unknown"),
                        "quality": Experience360Quality(
                            state="unknown", reasonCodes=[reason_code]
                        ),
                        "limitations": sorted(
                            set([*slot.limitations, "slot_provider_not_connected", reason_code])
                        ),
                        "reasonCodes": sorted(
                            set([*slot.reasonCodes, "slot_provider_not_connected", reason_code])
                        ),
                    }
                )
            )
        return frame.model_copy(
            update={
                "slots": unknown_slots,
                "warnings": sorted(set([*frame.warnings, reason_code])),
                "state": "unknown",
                "freshness": Experience360Freshness(state="unknown"),
                "quality": Experience360Quality(
                    state="unknown", reasonCodes=[reason_code]
                ),
            }
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


def _unique_provenance(
    provenance: Sequence[Experience360ProjectionProvenance],
) -> list[Experience360ProjectionProvenance]:
    """Preserve first-seen lineage while removing duplicate source records."""

    seen: set[tuple[object, ...]] = set()
    unique: list[Experience360ProjectionProvenance] = []
    for item in provenance:
        key = (
            item.tenantId,
            item.projectionId,
            item.sourceKind,
            item.sectionId,
            item.claimId,
            tuple(ref.model_dump_json(by_alias=True) for ref in item.evidenceRefs),
            tuple(item.canonicalAuthorityRefs),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _safe_member_role(value: object) -> Optional[str]:
    """Keep only bounded enum-like membership roles from graph properties."""

    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    role = value.strip()
    if (
        not role
        or len(role) > 64
        or not role.isascii()
        or not all(char.isalnum() or char in {"_", "-", "."} for char in role)
    ):
        return None
    return role


__all__ = [
    "ACCOUNT_AGENTS_SLOT",
    "ACCOUNT_MEMBERS_SLOT",
    "ACCOUNT_IDENTITY_SLOT",
    "Account360Provider",
    "Account360Source",
    "AccountIdentityRead",
    "AccountMember",
    "AccountMembersRead",
    "RepositoryAccount360Source",
    "SURFACE_ID",
]
