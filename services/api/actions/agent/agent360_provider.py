"""Read-only Agent360 projection over canonical agent and observation stores.

Agent360 is a governed projection, not an identity resolver, policy evaluator,
or execution authority. This provider reads tenant-scoped agent configuration,
execution/delegation repositories, and agentic observation rows. It never
executes work, writes graph state, upgrades source assertions to resolved
actors, or treats a stored grant as an effective authorization decision.

Agent identity is resolved only through a tenant-owned canonical Agent entity
or an explicit tenant-admin deployment identity binding. Authenticated human
principals are resolved separately through active tenant USER_ID aliases; this
does not resolve service principals or provide an effective authorization
decision. Bitemporal execution replay, full communication
history, independently measured outcomes, and cross-agent risk/contagion remain
delegated to their dedicated projections. Agent messages are included only
when they link through a tenant-scoped inbox record; this provider does not
infer message ownership or claim complete communication history.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    Experience360ActorParty,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from graph.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus
from shared.temporal.instant import try_parse_instant
from actions.agentic_observability.provenance import (
    AgentEvidenceReference,
    AgenticProvenanceQuery,
    read_agentic_provenance_records,
)


OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "interactions",
    "outcomes",
    "policy_boundary",
)

MAX_READ_LIMIT = 200
DEFAULT_READ_LIMIT = 100
# DelegationRepository.active_for() currently applies this fixed source cap and
# does not return its own truncation metadata.
ACTIVE_DELEGATION_REPOSITORY_LIMIT = 200
CAPABILITY_AUTHORIZATION_SCAN_LIMIT = 2000
CAPABILITY_AUTHORIZATION_READ_LIMIT = CAPABILITY_AUTHORIZATION_SCAN_LIMIT + 1

REASON_CONFIG_UNAVAILABLE = "agent_config_source_unavailable"
REASON_EXECUTION_UNAVAILABLE = "agent_execution_source_unavailable"
REASON_DELEGATION_UNAVAILABLE = "agent_delegation_source_unavailable"
REASON_ACTIVITY_UNAVAILABLE = "agent_activity_source_unavailable"
REASON_TOOL_UNAVAILABLE = "agent_tool_source_unavailable"
REASON_RISK_UNAVAILABLE = "agent_risk_source_unavailable"
REASON_COMMUNICATION_UNAVAILABLE = "agent_communication_source_unavailable"
REASON_TEMPORAL_REPLAY_UNAVAILABLE = "agent_temporal_replay_unavailable"
REASON_EVIDENCE_PROVENANCE_UNAVAILABLE = "agent_evidence_provenance_source_unavailable"


@dataclass(frozen=True)
class Agent360ReadBatch:
    """Bounded source read with explicit completeness and scope disposition."""

    rows: list[dict[str, Any]]
    truncated: bool = False
    scope_mismatch: bool = False
    scope_known: bool = True


class Agent360Source(Protocol):
    """Tenant-bounded canonical read seam used by :class:`Agent360Provider`.

    ``agent_id`` addresses agent configuration, execution, and observation
    records. Delegation methods receive a tenant-owned canonical Agent entity
    ID because their grantor/grantee columns are entity references.
    """

    async def agent_configs(self, tenant_id: str, agent_id: str) -> list[dict[str, Any]]: ...

    async def actor_identity(self, tenant_id: str, agent_id: str) -> Agent360ReadBatch: ...

    async def principal_identities(
        self, tenant_id: str, principal_user_ids: set[str], limit: int
    ) -> Agent360ReadBatch: ...

    async def executions(
        self, tenant_id: str, agent_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def incoming_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def outgoing_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def active_incoming_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str
    ) -> Agent360ReadBatch: ...

    async def delegation_party_identities(
        self, tenant_id: str, party_entity_ids: set[str]
    ) -> Agent360ReadBatch: ...

    async def activities(
        self, tenant_id: str, agent_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def tools(self, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]: ...

    async def capability_access_profile(
        self, tenant_id: str, agent_id: str, canonical_agent_entity_id: str
    ) -> Agent360ReadBatch: ...

    async def risk_signals(
        self, tenant_id: str, agent_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def agentic_provenance(
        self,
        tenant_id: str,
        agent_id: str,
        queries: list[AgenticProvenanceQuery],
        limit: int,
    ) -> Agent360ReadBatch: ...

    async def communications(
        self, tenant_id: str, agent_id: str, limit: int
    ) -> Agent360ReadBatch: ...


class RepositoryAgent360Source:
    """Default adapter over the existing agent and observation repositories.

    All reads include ``tenant_id`` in the repository filter. The source does
    not invoke graph mutation, policy evaluation, or agent runtime operations.
    """

    def __init__(self) -> None:
        # Imported here so importing the provider module itself stays light and
        # does not initialize repository clients or application services.
        from actions.agent.deployments import get_deployment_repository
        from actions.agent_marketplace.identity_binding import (
            AgentDeploymentIdentityBindingRepository,
        )
        from repositories.repos import (
            AgentConfigRepository,
            AgentExecutionRepository,
            DelegationRepository,
            EntityRepository,
        )
        from repositories.agentic_observability_repos import (
            AgentInboxRepository,
            AgentMessageRepository,
            AgentActivityRepository,
            AgentRiskSignalRepository,
            AgentToolRepository,
        )

        self._configs = AgentConfigRepository()
        self._executions = AgentExecutionRepository()
        self._delegations = DelegationRepository()
        self._deployments = get_deployment_repository()
        self._identity_bindings = AgentDeploymentIdentityBindingRepository()
        self._entities = EntityRepository()
        self._activities = AgentActivityRepository()
        self._tools = AgentToolRepository()
        self._risks = AgentRiskSignalRepository()
        self._inboxes = AgentInboxRepository()
        self._messages = AgentMessageRepository()
        self._principal_identity_repository: Any = None

    async def agent_configs(self, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        return await self._configs.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=2
        )

    async def actor_identity(self, tenant_id: str, agent_id: str) -> Agent360ReadBatch:
        """Resolve an agent only from its tenant-owned canonical identity evidence.

        The subject ID may already be the canonical Agent entity ID. Otherwise,
        source IDs are resolved through the tenant deployment registry and an
        explicit tenant-admin binding. If the bounded deployment scan is
        incomplete, the provider returns unknown instead of choosing a match.
        """
        from actions.agent.identity_resolution import resolve_agent_identities

        result = await resolve_agent_identities(
            tenant_id,
            {agent_id},
            deployments=self._deployments,
            identity_bindings=self._identity_bindings,
            entities=self._entities,
            limit=MAX_READ_LIMIT,
        )
        return Agent360ReadBatch(
            rows=result.rows,
            truncated=result.truncated,
            scope_mismatch=result.scope_mismatch,
        )

    async def delegation_party_identities(
        self, tenant_id: str, party_entity_ids: set[str]
    ) -> Agent360ReadBatch:
        """Resolve delegation party references only through tenant-owned entities."""
        if not tenant_id:
            return Agent360ReadBatch(rows=[], scope_known=False)
        requested = {
            value.strip()
            for value in party_entity_ids
            if isinstance(value, str) and value.strip()
        }
        if not requested:
            return Agent360ReadBatch(rows=[])
        raw_rows, truncated = await self._entities.find_many_for_tenant_entity_ids(
            tenant_id, requested
        )
        if not isinstance(raw_rows, list):
            raise TypeError("delegation party entity source returned an invalid contract")
        rows: list[dict[str, Any]] = []
        scope_mismatch = False
        for row in raw_rows:
            if not isinstance(row, dict):
                scope_mismatch = True
                continue
            entity_id = _first(row, "entity_id")
            if row.get("tenant_id") != tenant_id or entity_id not in requested:
                scope_mismatch = True
                continue
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "party_entity_id": entity_id,
                    "party_entity_type": row.get("entity_type"),
                    "identity_evidence_id": entity_id,
                    "identity_evidence_source": "entities",
                    "identity_observed_at": _first(row, "updated_at", "created_at"),
                }
            )
        return Agent360ReadBatch(
            rows=rows,
            truncated=truncated,
            scope_mismatch=scope_mismatch,
        )

    async def principal_identities(
        self, tenant_id: str, principal_user_ids: set[str], limit: int
    ) -> Agent360ReadBatch:
        """Resolve authenticated principal IDs through tenant USER_ID aliases.

        The raw authentication ID is only a source reference. It becomes a
        canonical Human entity only when the active tenant alias, survivor
        subject, and subject type all agree.
        """
        if not tenant_id:
            return Agent360ReadBatch(rows=[], scope_known=False)
        requested = sorted(
            {value.strip() for value in principal_user_ids if isinstance(value, str) and value.strip()}
        )
        if not requested:
            return Agent360ReadBatch(rows=[])
        bounded_limit = min(max(limit, 1), MAX_READ_LIMIT)
        truncated = len(requested) > bounded_limit
        requested = requested[:bounded_limit]
        if self._principal_identity_repository is None:
            from identity.identity.repository import IdentityResolutionRepository

            self._principal_identity_repository = IdentityResolutionRepository()
        from identity.identity.hashing import hash_value
        from identity.identity.models import IdentitySignalType

        repository = self._principal_identity_repository
        rows: list[dict[str, Any]] = []
        scope_mismatch = False
        for principal_user_id in requested:
            alias_hash = hash_value(principal_user_id, scope=f"user:{tenant_id}")
            aliases = await repository.find_aliases_by_signal(
                tenant_id,
                IdentitySignalType.USER_ID,
                alias_hash,
                limit=bounded_limit + 1,
            )
            if not isinstance(aliases, list):
                raise TypeError("principal identity source returned an invalid contract")
            if len(aliases) > bounded_limit:
                truncated = True
            surviving_ids: set[str] = set()
            for alias in aliases[:bounded_limit]:
                if (
                    not isinstance(alias, dict)
                    or alias.get("tenant_id") != tenant_id
                    or alias.get("alias_type") != IdentitySignalType.USER_ID.value
                    or alias.get("alias_value_hash") != alias_hash
                    or alias.get("revoked_at")
                    or alias.get("confidence_tier") != "deterministic"
                    or not isinstance(alias.get("canonical_entity_id"), str)
                ):
                    scope_mismatch = True
                    continue
                original_entity_id = alias["canonical_entity_id"]
                canonical_entity_id = await repository.resolve_surviving_canonical_entity_id(
                    tenant_id, original_entity_id
                )
                subject = await repository.get_subject_by_canonical_entity_id(
                    tenant_id, canonical_entity_id
                )
                if (
                    not isinstance(subject, dict)
                    or subject.get("tenant_id") != tenant_id
                    or subject.get("canonical_entity_id") != canonical_entity_id
                    or subject.get("entity_type") != "human"
                    or subject.get("status") != "active"
                ):
                    scope_mismatch = True
                    continue
                alias_id = _first(alias, "id")
                subject_id = _first(subject, "id")
                if alias_id is None or subject_id is None:
                    scope_mismatch = True
                    continue
                surviving_ids.add(canonical_entity_id)
                refs = [
                    EvidenceRef(
                        id=alias_id,
                        type="entity",
                        source="identity_aliases",
                        observedAt=_first(alias, "last_seen_at", "updated_at"),
                    ).model_dump(mode="json"),
                    EvidenceRef(
                        id=subject_id,
                        type="entity",
                        source="identity_subjects",
                        observedAt=_first(subject, "last_seen_at", "updated_at"),
                    ).model_dump(mode="json"),
                ]
                rows.append(
                    {
                        "tenant_id": tenant_id,
                        "principal_user_id": principal_user_id,
                        "canonical_human_entity_id": canonical_entity_id,
                        "identity_evidence_refs": refs,
                    }
                )
            if len(surviving_ids) > 1:
                scope_mismatch = True
        return Agent360ReadBatch(
            rows=rows,
            truncated=truncated,
            scope_mismatch=scope_mismatch,
        )

    async def executions(self, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]:
        return await self._executions.list_for_agent(agent_id, tenant_id, limit=limit + 1)

    async def incoming_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str, limit: int
    ) -> list[dict[str, Any]]:
        return await self._delegations.find_many(
            filters={
                "tenant_id": tenant_id,
                "grantee_entity_id": canonical_agent_entity_id,
            },
            limit=limit + 1,
        )

    async def outgoing_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str, limit: int
    ) -> list[dict[str, Any]]:
        return await self._delegations.find_many(
            filters={
                "tenant_id": tenant_id,
                "grantor_entity_id": canonical_agent_entity_id,
            },
            limit=limit + 1,
        )

    async def active_incoming_delegations(
        self, tenant_id: str, canonical_agent_entity_id: str
    ) -> Agent360ReadBatch:
        # This is the repository's own time/revocation-filtered active set. The
        # provider describes it as repository state, never as a policy verdict.
        # active_for() caps its backing query at 200 without exposing whether
        # that cap omitted additional grants, so a full result must be treated
        # as potentially incomplete.
        rows = await self._delegations.active_for(canonical_agent_entity_id, tenant_id)
        return Agent360ReadBatch(
            rows=rows,
            truncated=len(rows) >= ACTIVE_DELEGATION_REPOSITORY_LIMIT,
        )

    async def activities(self, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]:
        return await self._activities.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=limit + 1
        )

    async def tools(self, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]:
        return await self._tools.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=limit + 1
        )

    async def capability_access_profile(
        self, tenant_id: str, agent_id: str, canonical_agent_entity_id: str
    ) -> Agent360ReadBatch:
        """Read observed reach and exact canonical-agent grants through their authorities.

        Installations are keyed by the runtime agent reference, while capability
        authorizations are read by tenant plus the resolved canonical Agent entity.
        This is not an authorization decision for a new action/resource request.
        """
        from actions.agent_access_intelligence.authority import capability_authority_service
        from actions.agent_access_intelligence.profiles import capability_profile_service

        profile = await capability_profile_service.profile(tenant_id, agent_id)
        grants = await capability_authority_service.list(
            tenant_id=tenant_id,
            agent_id=canonical_agent_entity_id,
            limit=CAPABILITY_AUTHORIZATION_READ_LIMIT,
            offset=0,
        )
        truncated = len(grants) > CAPABILITY_AUTHORIZATION_SCAN_LIMIT
        return Agent360ReadBatch(
            rows=[
                {
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "canonical_agent_entity_id": canonical_agent_entity_id,
                    "profile": profile,
                    "canonical_grant_records": grants[:CAPABILITY_AUTHORIZATION_SCAN_LIMIT],
                    "canonical_grant_read_complete": not truncated,
                }
            ],
            truncated=truncated,
        )

    async def risk_signals(self, tenant_id: str, agent_id: str, limit: int) -> list[dict[str, Any]]:
        return await self._risks.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id}, limit=limit + 1
        )

    async def agentic_provenance(
        self,
        tenant_id: str,
        agent_id: str,
        queries: list[AgenticProvenanceQuery],
        limit: int,
    ) -> Agent360ReadBatch:
        if not tenant_id or not agent_id:
            return Agent360ReadBatch(rows=[], scope_known=False)
        foreign = [
            query
            for query in queries
            if query.evidence_ref.tenant_id != tenant_id
            or query.evidence_ref.agent_id != agent_id
        ]
        scoped_queries = [query for query in queries if query not in foreign]
        batch = await read_agentic_provenance_records(
            tenant_id=tenant_id,
            queries=scoped_queries[:limit],
        )
        return Agent360ReadBatch(
            rows=batch.rows,
            truncated=batch.truncated or len(scoped_queries) > limit,
            scope_mismatch=batch.scope_mismatch or bool(foreign),
            scope_known=batch.scope_known,
        )

    async def communications(self, tenant_id: str, agent_id: str, limit: int) -> Agent360ReadBatch:
        """Join observed messages to an agent only through its tenant inbox rows.

        Message rows have no ``agent_id`` of their own. The inbox record's
        tenant-scoped ``agent_id`` is an observed source reference, not a
        canonical identity binding; free-form message fields such as addresses
        and subjects are never used to resolve the agent.
        """
        inbox_limit = min(max(limit, 1), MAX_READ_LIMIT)
        raw_inboxes = await self._inboxes.find_many(
            filters={"tenant_id": tenant_id, "agent_id": agent_id},
            limit=inbox_limit + 1,
        )
        if not isinstance(raw_inboxes, list):
            raise TypeError("agent inbox source returned an invalid contract")

        truncated = len(raw_inboxes) > inbox_limit
        inboxes: list[dict[str, Any]] = []
        scope_mismatch = False
        for row in raw_inboxes[:inbox_limit]:
            if not isinstance(row, dict):
                scope_mismatch = True
                continue
            if row.get("tenant_id") != tenant_id or row.get("agent_id") != agent_id:
                scope_mismatch = True
                continue
            inbox_id = _first(row, "inbox_obs_id", "id")
            if inbox_id is None:
                scope_mismatch = True
                continue
            inbox_ref = _evidence_ref(
                row,
                source="obs_agent_inboxes",
                id_keys=("inbox_obs_id", "id"),
                time_keys=("observed_at", "received_at"),
            )
            if inbox_ref is None:
                scope_mismatch = True
                continue
            inboxes.append(
                {
                    **row,
                    "_resolved_inbox_id": inbox_id,
                    "_resolved_inbox_evidence_ref": inbox_ref.model_dump(mode="json"),
                }
            )

        messages: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for inbox in inboxes:
            remaining = limit - len(messages)
            if remaining <= 0:
                truncated = True
                break
            inbox_id = inbox["_resolved_inbox_id"]
            raw_messages = await self._messages.find_many(
                filters={"tenant_id": tenant_id, "inbox_obs_id": inbox_id},
                limit=remaining + 1,
            )
            if not isinstance(raw_messages, list):
                raise TypeError("agent message source returned an invalid contract")
            if len(raw_messages) > remaining:
                truncated = True
                raw_messages = raw_messages[:remaining]
            for row in raw_messages:
                if not isinstance(row, dict):
                    scope_mismatch = True
                    continue
                if row.get("tenant_id") != tenant_id or row.get("inbox_obs_id") != inbox_id:
                    scope_mismatch = True
                    continue
                message_id = _first(row, "message_obs_id", "id")
                if message_id is None:
                    scope_mismatch = True
                    continue
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                messages.append(
                    {
                        **row,
                        "agent_id": agent_id,
                        "subject_binding_basis": "exact_tenant_inbox_agent_id",
                        "inbox_evidence_ref": inbox["_resolved_inbox_evidence_ref"],
                    }
                )
        return Agent360ReadBatch(
            rows=messages[:limit],
            truncated=truncated or len(messages) > limit,
            scope_mismatch=scope_mismatch,
        )


@dataclass(frozen=True)
class _Read:
    rows: Optional[list[dict[str, Any]]]
    available: bool
    truncated: bool = False
    scope_mismatch: bool = False
    scope_known: bool = True


@dataclass(frozen=True)
class _TemporalSlice:
    rows: list[dict[str, Any]]
    omitted_undated: int = 0
    invalid_window: bool = False
    historical_replay_unavailable: bool = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(row: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _safe_strings(value: Any, *, cap: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:cap] if isinstance(item, (str, int))]


def _evidence_ref(
    row: dict[str, Any], *, source: str, id_keys: tuple[str, ...], time_keys: tuple[str, ...]
) -> Optional[EvidenceRef]:
    evidence_id = _first(row, *id_keys)
    if evidence_id is None:
        return None
    observed_at = _first(row, *time_keys)
    return EvidenceRef(
        id=evidence_id,
        type="entity"
        if source in {"agent_configs", "entities", "agent_deployment_identity_bindings"}
        else "relationship"
        if source == "delegations"
        else "event",
        source=source,
        observedAt=observed_at,
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _dedupe_json_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        source = ref.get("source")
        evidence_id = ref.get("id")
        if not isinstance(source, str) or not isinstance(evidence_id, str):
            continue
        key = (source, evidence_id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _safe_delegation(
    row: dict[str, Any], *, relation: str, active: bool, conflicted: bool = False
) -> dict[str, Any]:
    evidence_ref = _evidence_ref(
        row,
        source="delegations",
        id_keys=("delegation_id", "id"),
        time_keys=("starts_at",),
    )
    scope = row.get("scope")
    scope_view: Optional[dict[str, list[str]]] = None
    if isinstance(scope, dict):
        scope_view = {
            "actions": _safe_strings(scope.get("actions")),
            "resources": _safe_strings(scope.get("resources")),
        }
    return {
        "delegationId": _first(row, "delegation_id", "id"),
        "evidenceRef": evidence_ref.model_dump(mode="json") if evidence_ref else None,
        "relationToSubject": relation,
        "grantorEntityId": _first(row, "grantor_entity_id"),
        "granteeEntityId": _first(row, "grantee_entity_id"),
        "authorizationKind": _first(row, "authorization_kind"),
        "capabilityId": _first(row, "capability_id"),
        "serverRef": _first(row, "server_ref"),
        "capabilityObserved": (
            row.get("capability_observed")
            if isinstance(row.get("capability_observed"), bool)
            else None
        ),
        "scope": scope_view,
        "startsAt": _first(row, "starts_at"),
        "endsAt": _first(row, "ends_at"),
        "revokedAt": _first(row, "revoked_at"),
        "recordState": (
            "conflicted"
            if conflicted
            else "active_as_reported_by_repository"
            if active
            else "not_evaluated"
        ),
        "authorizationDecision": "unknown",
        "authorizationDecisionReason": (
            "stored delegation scope is evidence; effective action/resource policy was not evaluated"
        ),
    }


def _delegation_snapshot_differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Return authority-relevant fields that disagree across repository reads.

    ``active_for`` is cached, while ``find_many`` reads the canonical delegation row.
    Matching only by ID can therefore attach a stale active status to a newer revoked,
    expired, or scope-changed record. Keep the comparison limited to the fields that
    describe the delegation and its validity; repository metadata is not authority.
    """

    values = {
        "delegation_id": (
            _first(left, "delegation_id", "id"),
            _first(right, "delegation_id", "id"),
        ),
        "tenant_id": (left.get("tenant_id"), right.get("tenant_id")),
        "grantor_entity_id": (left.get("grantor_entity_id"), right.get("grantor_entity_id")),
        "grantee_entity_id": (left.get("grantee_entity_id"), right.get("grantee_entity_id")),
        "scope": (left.get("scope"), right.get("scope")),
        "authorization_kind": (left.get("authorization_kind"), right.get("authorization_kind")),
        "capability_id": (left.get("capability_id"), right.get("capability_id")),
        "server_ref": (left.get("server_ref"), right.get("server_ref")),
        "capability_observed": (
            left.get("capability_observed"),
            right.get("capability_observed"),
        ),
        "starts_at": (left.get("starts_at"), right.get("starts_at")),
        "ends_at": (left.get("ends_at"), right.get("ends_at")),
        "revoked_at": (left.get("revoked_at"), right.get("revoked_at")),
        "revoked_by_entity_id": (
            left.get("revoked_by_entity_id"),
            right.get("revoked_by_entity_id"),
        ),
    }
    return sorted(field for field, pair in values.items() if pair[0] != pair[1])


def _timestamp(row: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    return _first(row, *keys)


def _temporal_slice(
    rows: list[dict[str, Any]],
    *,
    request: ProjectionRequest,
    time_keys: tuple[str, ...],
) -> _TemporalSlice:
    """Apply event-time filters without claiming bitemporal reconstruction."""
    mode = request.temporalMode or "window"
    time_range = request.timeRange

    if mode in {"as_of", "compare"}:
        # These repositories do not provide a temporal replay/read-as-of API.
        # Do not present current rows as a reconstructed historical answer.
        return _TemporalSlice(rows=[], historical_replay_unavailable=True)

    lower = upper = None
    if time_range is not None:
        if time_range.from_:
            lower, error = try_parse_instant(time_range.from_)
            if error:
                return _TemporalSlice(rows=[], invalid_window=True)
        if time_range.to:
            upper, error = try_parse_instant(time_range.to)
            if error:
                return _TemporalSlice(rows=[], invalid_window=True)
    if lower is not None and upper is not None and upper < lower:
        return _TemporalSlice(rows=[], invalid_window=True)
    if lower is None and upper is None:
        return _TemporalSlice(rows=list(rows))

    selected: list[dict[str, Any]] = []
    omitted_undated = 0
    for row in rows:
        raw = _timestamp(row, time_keys)
        instant, error = try_parse_instant(raw) if raw is not None else (None, "timestamp_invalid")
        if error is not None or instant is None:
            omitted_undated += 1
            continue
        if lower is not None and instant < lower:
            continue
        if upper is not None and instant > upper:
            continue
        selected.append(row)
    return _TemporalSlice(rows=selected, omitted_undated=omitted_undated)


def _agentic_provenance_queries(
    *,
    tenant_id: str,
    agent_id: str,
    activities: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    risks: list[dict[str, Any]],
) -> tuple[list[AgenticProvenanceQuery], int, int]:
    """Build exact Bronze lookups from admitted compatibility rows only."""
    groups = (
        (
            activities,
            "obs_agent_activities",
            ("observation_id", "activity_id", "id"),
            ("observed_at", "occurred_at"),
            None,
        ),
        (
            tools,
            "obs_agent_tools",
            ("invocation_id", "tool_id", "id"),
            ("observed_at", "occurred_at"),
            "agent_tool_invocation_observed",
        ),
        (
            risks,
            "obs_agent_risk_signals",
            ("signal_id", "id"),
            ("detected_at", "observed_at"),
            "agent_risk_signal_observed",
        ),
    )
    queries: list[AgenticProvenanceQuery] = []
    unlinked = 0
    mismatched = 0
    for rows, source, id_keys, time_keys, fixed_event_type in groups:
        for row in rows:
            evidence_id = _first(row, *id_keys)
            event_id = row.get("canonical_event_id")
            schema_version = row.get("canonical_event_schema_version")
            event_type = fixed_event_type or _first(row, "event_name")
            if not event_id or not schema_version:
                unlinked += 1
                continue
            if (
                row.get("tenant_id") != tenant_id
                or row.get("agent_id") != agent_id
                or not isinstance(evidence_id, str)
                or not isinstance(event_id, str)
                or not isinstance(schema_version, str)
                or not isinstance(event_type, str)
            ):
                mismatched += 1
                continue
            try:
                reference = AgentEvidenceReference(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    source=source,
                    id=evidence_id,
                    observed_at=_timestamp(row, time_keys),
                    event_type=event_type,
                )
            except Exception:  # noqa: BLE001 - invalid refs cannot back an evidence claim
                mismatched += 1
                continue
            queries.append(
                AgenticProvenanceQuery(
                    bronze_event_id=event_id,
                    bronze_schema_version=schema_version,
                    evidence_ref=reference,
                )
            )
    return queries, unlinked, mismatched


class Agent360Provider:
    """Read-only, tenant-scoped IntelligenceProjectionProvider for ``agent360``."""

    projection_id = "agent360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, source: Optional[Agent360Source] = None) -> None:
        self._source = source if source is not None else RepositoryAgent360Source()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Compose evidence-backed agent sections; no writes or policy decisions."""
        if request.subject.kind not in {"agent", "entity"}:
            return self._unsupported_subject(request, context)

        if request.temporalMode in {"as_of", "compare"}:
            return self._unsupported_temporal_mode(request, context)

        tenant_id = request.tenantId
        agent_id = request.subject.id
        limit = min(
            max(request.page.limit if request.page else DEFAULT_READ_LIMIT, 1), MAX_READ_LIMIT
        )
        names = (
            "config",
            "actor_identity",
            "executions",
            "incoming_delegations",
            "outgoing_delegations",
            "active_delegations",
            "activities",
            "tools",
            "capability_access_profile",
            "risk_signals",
            "communications",
        )
        loaders = {
            "config": lambda: self._source.agent_configs(tenant_id, agent_id),
            "actor_identity": lambda: self._source.actor_identity(tenant_id, agent_id),
            "executions": lambda: self._source.executions(tenant_id, agent_id, limit),
            "incoming_delegations": lambda: self._source.incoming_delegations(
                tenant_id, agent_id, limit
            ),
            "outgoing_delegations": lambda: self._source.outgoing_delegations(
                tenant_id, agent_id, limit
            ),
            "active_delegations": lambda: self._source.active_incoming_delegations(
                tenant_id, agent_id
            ),
            "activities": lambda: self._source.activities(tenant_id, agent_id, limit),
            "tools": lambda: self._source.tools(tenant_id, agent_id, limit),
            "capability_access_profile": lambda: self._source.capability_access_profile(
                tenant_id, agent_id, delegation_agent_id or ""
            ),
            "risk_signals": lambda: self._source.risk_signals(tenant_id, agent_id, limit),
            "communications": lambda: self._source.communications(tenant_id, agent_id, limit),
        }
        # Resolve identity before delegation reads. Agent executions/configs
        # use their runtime/source ID, while grantor/grantee references use a
        # canonical entity ID. Reading delegations with the source ID can make
        # real authority records look like an empty grant set.
        identity_prefetched = await self._safe_read(
            "actor_identity", loaders["actor_identity"], limit
        )
        identity_rows, identity_mismatch = self._tenant_agent_identity(
            identity_prefetched, tenant_id, agent_id
        )
        canonical_actor_ids = {
            row["canonical_agent_entity_id"]
            for row in identity_rows
            if isinstance(row.get("canonical_agent_entity_id"), str)
        }
        delegation_agent_id = (
            next(iter(canonical_actor_ids))
            if identity_prefetched.available
            and not identity_prefetched.truncated
            and not identity_mismatch
            and identity_prefetched.scope_known
            and len(canonical_actor_ids) == 1
            else None
        )

        if request.subject.kind == "entity":
            is_canonical_agent = (
                delegation_agent_id == agent_id
                and len(identity_rows) == 1
                and identity_rows[0].get("identity_binding_authority") == "canonical_agent_entity"
            )
            if not is_canonical_agent:
                return self._unsupported_subject(
                    request,
                    context,
                    reason=(
                        "entity subject is not verified as the tenant-owned canonical Agent entity"
                    ),
                    degraded_reason="agent_entity_subject_unresolved",
                )

        async def unresolved_delegation_read() -> Agent360ReadBatch:
            # No canonical party means delegation absence cannot be asserted.
            return Agent360ReadBatch(rows=[], scope_known=False)

        delegation_id = delegation_agent_id or ""
        loaders["incoming_delegations"] = lambda: (
            self._source.incoming_delegations(tenant_id, delegation_id, limit)
            if delegation_agent_id is not None
            else unresolved_delegation_read()
        )
        loaders["outgoing_delegations"] = lambda: (
            self._source.outgoing_delegations(tenant_id, delegation_id, limit)
            if delegation_agent_id is not None
            else unresolved_delegation_read()
        )
        loaders["active_delegations"] = lambda: (
            self._source.active_incoming_delegations(tenant_id, delegation_id)
            if delegation_agent_id is not None
            else unresolved_delegation_read()
        )
        async def not_applicable_capability_profile() -> Agent360ReadBatch:
            # Capability installations are keyed by the runtime agent reference.
            # An entity subject has no exact runtime-id join in this provider.
            return Agent360ReadBatch(
                rows=[
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "not_applicable": True,
                        "profile": None,
                    }
                ]
            )

        if request.subject.kind != "agent":
            loaders["capability_access_profile"] = not_applicable_capability_profile
        elif delegation_agent_id is None:
            async def unresolved_capability_profile() -> Agent360ReadBatch:
                return Agent360ReadBatch(rows=[], scope_known=False)

            loaders["capability_access_profile"] = unresolved_capability_profile

        names_to_read = tuple(name for name in names if name != "actor_identity")
        reads = await asyncio.gather(
            *(self._safe_read(name, loaders[name], limit) for name in names_to_read)
        )
        data = dict(zip(names_to_read, reads))
        if identity_prefetched is not None:
            data["actor_identity"] = identity_prefetched
        execution_rows_for_identity, _ = self._tenant_agent_rows(
            data["executions"], tenant_id, agent_id
        )
        principal_user_ids = {
            principal_id
            for row in execution_rows_for_identity
            if (principal_id := _first(row, "initiating_principal_user_id")) is not None
        }
        if principal_user_ids:
            principal_identity_read = await self._safe_read(
                "principal_identities",
                lambda: self._source.principal_identities(
                    tenant_id, principal_user_ids, limit
                ),
                limit,
            )
        else:
            principal_identity_read = _Read(rows=[], available=True)
        data["principal_identities"] = principal_identity_read
        degraded_reasons = [
            self._reason_for(name) for name, read in data.items() if not read.available
        ]
        degraded_reasons.extend(
            f"{name}_read_truncated" for name, read in data.items() if read.truncated
        )

        config_rows, config_mismatch = self._tenant_agent_rows(data["config"], tenant_id, agent_id)
        actor_identity_rows, actor_identity_mismatch = self._tenant_agent_identity(
            data["actor_identity"], tenant_id, agent_id
        )
        canonical_actor_ids = {row["canonical_agent_entity_id"] for row in actor_identity_rows}
        actor_identity_conflict = len(canonical_actor_ids) > 1
        actor_identity_read_complete = (
            data["actor_identity"].available
            and not data["actor_identity"].truncated
            and not actor_identity_mismatch
            and data["actor_identity"].scope_known
        )
        resolved_canonical_actor = (
            next(iter(canonical_actor_ids))
            if actor_identity_read_complete and len(canonical_actor_ids) == 1
            else None
        )
        actor_identity_state = (
            "conflicted"
            if actor_identity_conflict or actor_identity_mismatch
            else "matched"
            if resolved_canonical_actor is not None
            else "unknown"
        )
        actor_identity_refs = [
            ref.model_dump(mode="json")
            for row in actor_identity_rows
            if (
                ref := self._ref_one(
                    row,
                    row["identity_evidence_source"],
                    ("identity_evidence_id",),
                    ("identity_bound_at",),
                )
            )
        ]
        execution_rows, execution_mismatch = self._tenant_agent_rows(
            data["executions"], tenant_id, agent_id
        )
        activity_rows, activity_mismatch = self._tenant_agent_rows(
            data["activities"], tenant_id, agent_id
        )
        tool_rows, tool_mismatch = self._tenant_agent_rows(data["tools"], tenant_id, agent_id)
        risk_rows, risk_mismatch = self._tenant_agent_rows(
            data["risk_signals"], tenant_id, agent_id
        )
        communication_rows, communication_mismatch = self._tenant_agent_communications(
            data["communications"], tenant_id, agent_id
        )
        incoming_rows, incoming_mismatch = self._tenant_delegation_rows(
            data["incoming_delegations"],
            tenant_id,
            delegation_agent_id or "",
            "grantee_entity_id",
        )
        outgoing_rows, outgoing_mismatch = self._tenant_delegation_rows(
            data["outgoing_delegations"],
            tenant_id,
            delegation_agent_id or "",
            "grantor_entity_id",
        )
        active_rows, active_mismatch = self._tenant_delegation_rows(
            data["active_delegations"],
            tenant_id,
            delegation_agent_id or "",
            "grantee_entity_id",
        )
        principal_identity_rows, principal_identity_mismatch = (
            self._tenant_principal_identity_rows(
                data["principal_identities"], tenant_id, principal_user_ids
            )
        )
        capability_profile_rows, capability_profile_mismatch = (
            self._tenant_capability_access_profile_rows(
                data["capability_access_profile"],
                tenant_id,
                agent_id,
                delegation_agent_id,
            )
        )
        capability_profile_complete = self._capability_profile_complete(
            capability_profile_rows,
            data["capability_access_profile"],
            scope_mismatch=capability_profile_mismatch,
        )
        if capability_profile_rows and capability_profile_rows[0].get("not_applicable") is True:
            capability_profile_complete = True
        source_scope_mismatches = {
            "config": config_mismatch,
            "actor_identity": actor_identity_mismatch,
            "executions": execution_mismatch,
            "activities": activity_mismatch,
            "tools": tool_mismatch,
            "risk_signals": risk_mismatch,
            "communications": communication_mismatch,
            "incoming_delegations": incoming_mismatch,
            "outgoing_delegations": outgoing_mismatch,
            "active_delegations": active_mismatch,
            "principal_identities": principal_identity_mismatch,
            "capability_access_profile": capability_profile_mismatch,
        }
        data = {
            name: replace(read, scope_mismatch=read.scope_mismatch or source_scope_mismatches[name])
            for name, read in data.items()
        }
        data["capability_access_profile"] = replace(
            data["capability_access_profile"],
            scope_known=(
                data["capability_access_profile"].scope_known
                and capability_profile_complete
                and not capability_profile_mismatch
            ),
        )
        scope_mismatch = actor_identity_conflict or any(
            read.scope_mismatch for read in data.values()
        )
        execution_principals = self._execution_principals(execution_rows, read=data["executions"])
        execution_principal_identity = self._resolve_execution_principal_identity(
            execution_principals,
            read=data["principal_identities"],
            identity_rows=principal_identity_rows,
        )

        config = config_rows[0] if len(config_rows) == 1 else None
        config_conflict = len(config_rows) > 1
        if config_conflict:
            degraded_reasons.append("agent_config_identity_conflict")
        if actor_identity_conflict:
            degraded_reasons.append("agent_identity_binding_conflict")
        elif resolved_canonical_actor is None and any(
            (
                config_rows,
                execution_rows,
                activity_rows,
                tool_rows,
                risk_rows,
                communication_rows,
            )
        ):
            degraded_reasons.append("agent_identity_binding_unresolved")
        if scope_mismatch:
            degraded_reasons.append("agent_source_scope_mismatch")

        active_ids = {
            _first(row, "delegation_id", "id")
            for row in active_rows
            if _first(row, "delegation_id", "id") is not None
        }
        active_rows_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in active_rows:
            row_id = _first(row, "delegation_id", "id")
            if row_id is not None:
                active_rows_by_id.setdefault(row_id, []).append(row)

        active_delegation_conflicts: dict[str, dict[str, Any]] = {}
        for row in incoming_rows:
            row_id = _first(row, "delegation_id", "id")
            if row_id is None:
                continue
            active_variants = active_rows_by_id.get(row_id, [])
            differing_fields = sorted(
                {
                    field
                    for active_row in active_variants
                    for field in _delegation_snapshot_differences(row, active_row)
                }
            )
            if not differing_fields:
                continue
            refs = [
                ref.model_dump(mode="json")
                for candidate in [row, *active_variants]
                if (
                    ref := self._ref_one(
                        candidate,
                        "delegations",
                        ("delegation_id", "id"),
                        ("starts_at",),
                    )
                )
            ]
            active_delegation_conflicts[row_id] = {
                "delegationId": row_id,
                "state": "conflicted",
                "differingFields": differing_fields,
                "reason": (
                    "tenant-scoped delegation and active-set repository reads disagreed; "
                    "active status is unknown"
                ),
                "evidenceRefs": _dedupe_json_refs(refs),
            }
        delegation_records: list[tuple[dict[str, Any], str, bool]] = []
        seen_delegation_ids: set[str] = set()
        for row in incoming_rows:
            row_id = _first(row, "delegation_id", "id")
            if row_id is not None and row_id not in seen_delegation_ids:
                seen_delegation_ids.add(row_id)
                delegation_records.append(
                    (
                        row,
                        "incoming",
                        row_id in active_ids and row_id not in active_delegation_conflicts,
                    )
                )
        for row in outgoing_rows:
            row_id = _first(row, "delegation_id", "id")
            if row_id is not None and row_id not in seen_delegation_ids:
                seen_delegation_ids.add(row_id)
                delegation_records.append((row, "outgoing", False))

        canonical_delegations: dict[str, dict[str, Any]] = {}
        ambiguous_delegation_ids: set[str] = set()
        for row in [*incoming_rows, *outgoing_rows]:
            row_id = _first(row, "delegation_id", "id")
            if row_id is None or row_id in ambiguous_delegation_ids:
                continue
            existing = canonical_delegations.get(row_id)
            if existing is not None and existing != row:
                canonical_delegations.pop(row_id, None)
                ambiguous_delegation_ids.add(row_id)
            else:
                canonical_delegations[row_id] = row

        delegation_party_entity_ids = {
            entity_id
            for row, _, _ in delegation_records
            for field in ("grantor_entity_id", "grantee_entity_id")
            if (entity_id := _first(row, field)) is not None
        }
        if delegation_party_entity_ids:
            party_identity_read = await self._safe_read(
                "delegation_parties",
                lambda: self._source.delegation_party_identities(
                    tenant_id, delegation_party_entity_ids
                ),
                len(delegation_party_entity_ids) + 1,
            )
        else:
            party_identity_read = _Read(rows=[], available=True)
        party_identity_rows, party_identity_mismatch = (
            self._tenant_delegation_party_identity_rows(
                party_identity_read, tenant_id, delegation_party_entity_ids
            )
        )
        party_identity_read = replace(
            party_identity_read,
            scope_mismatch=party_identity_read.scope_mismatch or party_identity_mismatch,
        )
        data["delegation_parties"] = party_identity_read
        scope_mismatch = scope_mismatch or party_identity_read.scope_mismatch
        if not party_identity_read.available:
            degraded_reasons.append("agent_delegation_party_identity_source_unavailable")
        if party_identity_read.truncated:
            degraded_reasons.append("agent_delegation_party_identity_read_truncated")
        if not party_identity_read.scope_known:
            degraded_reasons.append("agent_delegation_party_identity_scope_unknown")
        if party_identity_read.scope_mismatch:
            degraded_reasons.append("agent_delegation_party_identity_scope_mismatch")
        party_identity_rows_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in party_identity_rows:
            entity_id = _first(row, "party_entity_id")
            if entity_id is not None:
                party_identity_rows_by_id.setdefault(entity_id, []).append(row)

        timeline_exec = _temporal_slice(
            execution_rows, request=request, time_keys=("started_at", "created_at")
        )
        timeline_activity = _temporal_slice(
            activity_rows, request=request, time_keys=("observed_at", "occurred_at")
        )
        timeline_tools = _temporal_slice(
            tool_rows, request=request, time_keys=("observed_at", "occurred_at")
        )
        timeline_risks = _temporal_slice(
            risk_rows, request=request, time_keys=("detected_at", "observed_at")
        )
        timeline_communications = _temporal_slice(
            communication_rows, request=request, time_keys=("observed_at", "received_at")
        )
        historical_unavailable = any(
            item.historical_replay_unavailable
            for item in (
                timeline_exec,
                timeline_activity,
                timeline_tools,
                timeline_risks,
                timeline_communications,
            )
        )
        invalid_window = any(
            item.invalid_window
            for item in (
                timeline_exec,
                timeline_activity,
                timeline_tools,
                timeline_risks,
                timeline_communications,
            )
        )
        temporal_omitted = sum(
            item.omitted_undated
            for item in (
                timeline_exec,
                timeline_activity,
                timeline_tools,
                timeline_risks,
                timeline_communications,
            )
        )
        if historical_unavailable:
            degraded_reasons.append(REASON_TEMPORAL_REPLAY_UNAVAILABLE)
        if invalid_window:
            degraded_reasons.append("agent_temporal_window_invalid")

        provenance_queries, unlinked_provenance_rows, invalid_provenance_rows = (
            _agentic_provenance_queries(
                tenant_id=tenant_id,
                agent_id=agent_id,
                activities=timeline_activity.rows,
                tools=timeline_tools.rows,
                risks=timeline_risks.rows,
            )
        )
        provenance_loader = getattr(self._source, "agentic_provenance", None)
        if not provenance_queries:
            provenance_read = _Read(rows=[], available=True)
        elif callable(provenance_loader):
            provenance_read = await self._safe_read(
                "agentic_provenance",
                lambda: provenance_loader(
                    tenant_id,
                    agent_id,
                    provenance_queries,
                    min(len(provenance_queries), 3 * MAX_READ_LIMIT),
                ),
                min(len(provenance_queries), 3 * MAX_READ_LIMIT),
            )
        else:
            provenance_read = _Read(rows=None, available=False)
        data["agentic_provenance"] = provenance_read
        provenance_rows = provenance_read.rows or []
        provenance_by_event = {
            row.get("bronze_event_id"): row
            for row in provenance_rows
            if isinstance(row.get("bronze_event_id"), str)
        }
        exact_provenance_count = sum(
            1
            for query in provenance_queries
            if query.bronze_event_id in provenance_by_event
        )
        unresolved_provenance_links = max(0, len(provenance_queries) - exact_provenance_count)
        provenance_scope_mismatch = (
            invalid_provenance_rows > 0 or provenance_read.scope_mismatch
        )
        scope_mismatch = scope_mismatch or provenance_scope_mismatch
        if not provenance_read.available:
            degraded_reasons.append(REASON_EVIDENCE_PROVENANCE_UNAVAILABLE)
        if provenance_read.truncated:
            degraded_reasons.append("agent_evidence_provenance_read_truncated")
        if provenance_scope_mismatch:
            degraded_reasons.append("agent_evidence_provenance_scope_mismatch")
        if unlinked_provenance_rows or unresolved_provenance_links:
            degraded_reasons.append("agent_evidence_provenance_links_incomplete")

        evidence_refs, evidence_rows_missing = self._collect_evidence(
            config_rows=config_rows,
            agent_identities=actor_identity_rows,
            executions=execution_rows,
            delegations=delegation_records,
            delegation_party_identities=party_identity_rows,
            activities=activity_rows,
            tools=tool_rows,
            risks=risk_rows,
            communications=timeline_communications.rows,
            principal_identities=principal_identity_rows,
        )
        if historical_unavailable or invalid_window:
            claim_evidence_refs: list[EvidenceRef] = []
        elif request.timeRange is not None:
            # Current config, grants, and identity rows cannot be replayed into
            # an event-time window. Claim only refs from rows admitted by the
            # temporal slices, without broadening the existing evidence view.
            claim_evidence_refs, _ = self._collect_evidence(
                config_rows=[],
                agent_identities=[],
                principal_identities=[],
                executions=timeline_exec.rows,
                delegations=[],
                delegation_party_identities=[],
                activities=timeline_activity.rows,
                tools=timeline_tools.rows,
                risks=timeline_risks.rows,
                communications=timeline_communications.rows,
            )
        else:
            claim_evidence_refs = evidence_refs

        bronze_evidence_refs: list[EvidenceRef] = []
        for row in provenance_rows:
            try:
                bronze_evidence_refs.append(
                    EvidenceRef.model_validate(row.get("bronze_evidence_ref"))
                )
            except Exception:  # noqa: BLE001 - malformed refs cannot back an evidence claim
                provenance_scope_mismatch = True
                degraded_reasons.append("agent_evidence_provenance_scope_mismatch")
        if provenance_scope_mismatch:
            scope_mismatch = True
            data["agentic_provenance"] = replace(
                data["agentic_provenance"], scope_mismatch=True
            )
            provenance_read = data["agentic_provenance"]
        evidence_refs = _dedupe_refs(evidence_refs + bronze_evidence_refs)
        if claim_evidence_refs:
            claim_evidence_refs = _dedupe_refs(claim_evidence_refs + bronze_evidence_refs)

        agentic_provenance_state = (
            "empty"
            if not (timeline_activity.rows or timeline_tools.rows or timeline_risks.rows)
            and provenance_read.available
            else "partial"
        )
        record_freshness_states = {
            row.get("freshness_state")
            for row in provenance_rows
            if row.get("freshness_state") in {"not_assessed", "undated"}
        }
        freshness_state = (
            "not_assessed"
            if "not_assessed" in record_freshness_states
            else "undated"
            if record_freshness_states
            else "not_assessed"
        )
        agentic_provenance_content = {
            "state": agentic_provenance_state,
            "lineageState": (
                "verified"
                if provenance_queries
                and exact_provenance_count == len(provenance_queries)
                and not provenance_scope_mismatch
                and not provenance_read.truncated
                else "partial"
                if timeline_activity.rows or timeline_tools.rows or timeline_risks.rows
                else "unknown"
            ),
            "records": provenance_rows,
            "exactBronzeLinks": exact_provenance_count,
            "unlinkedCompatibilityRows": unlinked_provenance_rows,
            "unresolvedLinks": unresolved_provenance_links + invalid_provenance_rows,
            "sourceIdentityState": "unresolved",
            "sourceTrust": "unknown",
            "freshness": {
                "state": freshness_state,
                "slaSeconds": None,
                "reason": "agentic_source_freshness_sla_not_configured",
            },
            "reason": (
                "Bronze links are exact tenant, event, schema, agent, source-row, and event-time references. The provider claim is not joined to a registered Rights source, and no source freshness SLA is configured."
            ),
        }

        source_states = {name: self._read_state(read) for name, read in data.items()}
        config_ref = (
            self._ref_one(config, "agent_configs", ("agent_id",), ("created_at",))
            if config
            else None
        )
        identity_state = (
            "conflicted"
            if config_conflict or actor_identity_conflict
            else "available"
            if config is not None or resolved_canonical_actor is not None
            else "unknown"
        )
        identity_content: dict[str, Any] = {
            "state": identity_state,
            "agentId": agent_id if config is not None else None,
            "canonicalAgentEntityId": resolved_canonical_actor,
            "model": config.get("model") if config is not None else None,
            "status": config.get("status") if config is not None else None,
            "registeredAt": config.get("created_at") if config is not None else None,
            "configuredTools": _safe_strings(config.get("tools")) if config is not None else None,
            "configuredOwnerEntityId": config.get("owner_entity_id")
            if config is not None
            else None,
            "evidenceRefs": actor_identity_refs
            + ([config_ref.model_dump(mode="json")] if config_ref else []),
            "reason": (
                "multiple tenant-scoped configuration records matched; identity is not selected"
                if config_conflict
                else "canonical agent identity resolution is unavailable"
                if not data["actor_identity"].available
                else "no tenant-scoped agent configuration record was found"
                if config is None
                else None
            ),
        }

        actor_attribution = {
            "state": actor_identity_state,
            "assertedSourceActor": agent_id,
            "configuredOwnerEntityId": (
                str(config.get("owner_entity_id"))
                if config is not None and config.get("owner_entity_id")
                else None
            ),
            "resolvedCanonicalActor": resolved_canonical_actor,
            "executionPrincipal": execution_principals["executionPrincipal"],
            "executionPrincipalState": execution_principals["state"],
            "executionPrincipalCandidates": execution_principal_identity["candidates"],
            "executionPrincipalEvidenceRefs": execution_principals["evidenceRefs"],
            "executionPrincipalCanonicalIdentity": execution_principal_identity[
                "canonicalIdentity"
            ],
            "delegator": None,
            "delegatee": None,
            "authorityDecision": "unknown",
            "evidenceRefs": _dedupe_json_refs(
                actor_identity_refs
                + ([config_ref.model_dump(mode="json")] if config_ref else [])
                + execution_principals["evidenceRefs"]
                + execution_principal_identity["evidenceRefs"]
            ),
            "reason": (
                "multiple tenant-owned identity bindings resolve this source reference to different canonical Agents"
                if actor_identity_conflict
                else "canonical agent identity resolution is unavailable"
                if not data["actor_identity"].available
                else "the bounded tenant deployment identity scan is incomplete"
                if data["actor_identity"].truncated
                else "identity binding scope validation failed"
                if actor_identity_mismatch
                else (
                    "the source reference resolves to a tenant-owned canonical Agent; "
                    f"authenticated principal identity state is "
                    f"{execution_principal_identity['canonicalIdentity']['state']}; "
                    "action authorization remains unknown"
                )
                if resolved_canonical_actor is not None
                else "owner_entity_id is a configuration assertion and no tenant-owned canonical Agent binding was found"
            ),
        }

        delegation_party_views: dict[tuple[str, str], dict[str, Any]] = {}
        delegation_items: list[dict[str, Any]] = []
        for row, relation, active in delegation_records:
            delegation_id = _first(row, "delegation_id", "id")
            delegation_evidence_ref = self._ref_one(
                row, "delegations", ("delegation_id", "id"), ("starts_at",)
            )
            side_views: dict[str, dict[str, Any]] = {}
            for side, field in (
                ("grantor", "grantor_entity_id"),
                ("grantee", "grantee_entity_id"),
            ):
                view = self._delegation_party_identity_view(
                    _first(row, field),
                    read=party_identity_read,
                    identity_rows_by_id=party_identity_rows_by_id,
                    delegation_evidence_ref=delegation_evidence_ref,
                )
                side_views[side] = view
                if delegation_id is not None:
                    delegation_party_views[(delegation_id, side)] = view
            item = _safe_delegation(
                row,
                relation=relation,
                active=active,
                conflicted=delegation_id in active_delegation_conflicts,
            )
            item["grantorParty"] = side_views["grantor"]
            item["granteeParty"] = side_views["grantee"]
            if len(delegation_items) < limit:
                delegation_items.append(item)
        action_scoped_decisions = [
            decision
            for row in execution_rows[:limit]
            if (
                decision := self._recorded_execution_decision(
                    row, canonical_delegations=canonical_delegations
                )
            )
            is not None
        ]
        authority_state = self._aggregate_read_state(
            [
                data["incoming_delegations"],
                data["outgoing_delegations"],
                data["active_delegations"],
                data["executions"],
                data["delegation_parties"],
                data["capability_access_profile"],
            ],
            has_rows=bool(
                delegation_items
                or action_scoped_decisions
                or (
                    capability_profile_complete
                    and capability_profile_rows
                    and capability_profile_rows[0].get("not_applicable") is not True
                )
            ),
        )
        if active_delegation_conflicts:
            authority_state = "degraded"
            degraded_reasons.append("agent_delegation_active_record_conflict")
        unresolved_party_identity = any(
            view["state"] == "unknown" for view in delegation_party_views.values()
        )
        conflicted_party_identity = any(
            view["state"] == "conflicted" for view in delegation_party_views.values()
        )
        if unresolved_party_identity or conflicted_party_identity:
            authority_state = "degraded"
            if unresolved_party_identity:
                degraded_reasons.append("agent_delegation_party_identity_unresolved")
            if conflicted_party_identity:
                degraded_reasons.append("agent_delegation_party_identity_conflicted")
        unresolved_delegation_reference = any(
            decision["delegationReferenceState"] == "unresolved"
            for decision in action_scoped_decisions
        )
        conflicted_delegation_reference = any(
            decision["delegationReferenceState"] == "conflicted"
            for decision in action_scoped_decisions
        )
        if unresolved_delegation_reference or conflicted_delegation_reference:
            if authority_state == "available":
                authority_state = "degraded"
            if unresolved_delegation_reference:
                degraded_reasons.append("agent_execution_delegation_reference_unresolved")
            if conflicted_delegation_reference:
                degraded_reasons.append("agent_execution_delegation_reference_conflicted")
        capability_access_profile_view = self._capability_access_profile_view(
            capability_profile_rows,
            data["capability_access_profile"],
            scope_mismatch=capability_profile_mismatch,
            tenant_id=tenant_id,
        )
        authority_content = {
            "state": authority_state,
            "delegationRecords": delegation_items,
            "delegationReadConflicts": list(active_delegation_conflicts.values()),
            "actionScopedDecisions": action_scoped_decisions,
            "actionScopedDecisionState": self._aggregate_read_state(
                [data["executions"]], has_rows=bool(action_scoped_decisions)
            ),
            "effectiveAuthorizationDecision": "unknown",
            "capabilityAccessProfile": capability_access_profile_view,
            "decisionReason": (
                "recorded execution decisions describe only the action and resource evaluated "
                "at request time; stored delegation records do not authorize a new action. "
                "A delegation reference is canonically matched only when the execution and "
                "policy-log IDs agree and a tenant-scoped record matches the canonical Agent"
            ),
            "activeIncomingCount": (
                None
                if active_delegation_conflicts
                else self._count(data["active_delegations"], active_rows)
            ),
            "temporalSemantics": "current_repository_state; no historical replay",
            "truncated": any(
                data[name].truncated
                for name in (
                    "incoming_delegations",
                    "outgoing_delegations",
                    "active_delegations",
                    "executions",
                    "delegation_parties",
                )
            ),
            "evidenceRefs": [
                ref.model_dump(mode="json")
                for row, _, _ in delegation_records
                if (
                    ref := self._ref_one(
                        row, "delegations", ("delegation_id", "id"), ("starts_at",)
                    )
                )
            ]
            + [
                ref.model_dump(mode="json")
                for row in party_identity_rows
                if (
                    ref := self._ref_one(
                        row,
                        "entities",
                        ("identity_evidence_id",),
                        ("identity_observed_at",),
                    )
                )
            ],
        }

        risk_items = [
            {
                "signalId": _first(row, "signal_id", "id"),
                "riskLevel": _first(row, "risk_level"),
                "reasonCodes": _safe_strings(row.get("reason_codes")),
                "policyFlags": _safe_strings(row.get("policy_flags")),
                "detectedAt": _first(row, "detected_at", "observed_at"),
                "evidenceRef": (
                    self._ref_one(
                        row,
                        "obs_agent_risk_signals",
                        ("signal_id", "id"),
                        ("detected_at", "observed_at"),
                    ).model_dump(mode="json")
                    if self._ref_one(
                        row,
                        "obs_agent_risk_signals",
                        ("signal_id", "id"),
                        ("detected_at", "observed_at"),
                    )
                    else None
                ),
            }
            for row in timeline_risks.rows[:limit]
        ]
        communication_items = [
            self._communication_view(row) for row in timeline_communications.rows[:limit]
        ]

        exec_items = [self._execution_view(row) for row in execution_rows[:limit]]
        activity_items = [self._activity_view(row) for row in timeline_activity.rows[:limit]]
        tool_items = [self._tool_view(row) for row in timeline_tools.rows[:limit]]
        timeline_items = (
            [
                {
                    "kind": "execution",
                    "timestamp": _first(row, "started_at", "created_at"),
                    **self._execution_view(row),
                }
                for row in timeline_exec.rows[:limit]
            ]
            + [{"kind": "agentic_observation", **item} for item in activity_items]
            + [{"kind": "tool_invocation", **item} for item in tool_items]
            + [{"kind": "agent_message_observation", **item} for item in communication_items]
        )
        timeline_items.sort(key=lambda item: item.get("timestamp") or item.get("observedAt") or "")

        all_sources_available = all(read.available for read in data.values())
        any_sources_available = any(read.available for read in data.values())
        incomplete_reads = any(
            not read.available or read.truncated or read.scope_mismatch or not read.scope_known
            for read in data.values()
        )
        any_agent_evidence = bool(
            config_rows
            or actor_identity_rows
            or execution_rows
            or activity_rows
            or tool_rows
            or risk_rows
            or communication_rows
            or delegation_records
        )
        identity_unresolved_with_evidence = resolved_canonical_actor is None and any_agent_evidence
        if (
            not any_sources_available
            or any(
                not read.available or read.truncated or read.scope_mismatch
                for read in data.values()
            )
            or scope_mismatch
            or identity_unresolved_with_evidence
        ):
            summary_state = "degraded"
        elif any_agent_evidence:
            summary_state = "available"
        else:
            summary_state = "unknown"

        summary_section = ProjectionSection(
            id="summary",
            state=summary_state,  # type: ignore[arg-type]
            title="Agent observation summary",
            content={
                "subject": {"kind": request.subject.kind, "id": agent_id},
                "profileKnown": config is not None,
                "identity": identity_content,
                "sourceStates": source_states,
                "counts": {
                    "executions": self._count(data["executions"], execution_rows),
                    "delegationRecords": self._count(
                        _merge_reads(data["incoming_delegations"], data["outgoing_delegations"]),
                        delegation_records,
                    ),
                    "activities": self._count(data["activities"], activity_rows),
                    "toolInvocations": self._count(data["tools"], tool_rows),
                    "riskSignals": self._count(data["risk_signals"], risk_rows),
                    "communicationMessages": self._count(
                        data["communications"], communication_rows
                    ),
                },
                "truncatedSources": [name for name, read in data.items() if read.truncated],
                "unsupportedSlots": self._unsupported_slots(),
                "interpretation": (
                    "Counts describe bounded tenant-scoped repository reads. They do not imply "
                    "complete history when a source is truncated, unavailable, or has cross-scope rows omitted."
                ),
            },
            warnings=self._warnings(data, scope_mismatch, evidence_rows_missing),
        )

        state_section = ProjectionSection(
            id="state",
            state="degraded"
            if incomplete_reads or scope_mismatch or not any_sources_available
            else "available",  # type: ignore[arg-type]
            title="Agent identity, authority, and observed posture",
            content={
                "dimensions": [
                    {"id": "agent_identity", "state": identity_state, "content": identity_content},
                    {
                        "id": "actor_attribution",
                        "state": actor_identity_state,
                        "content": actor_attribution,
                    },
                    {
                        "id": "authority_and_delegation",
                        "state": authority_state,
                        "content": authority_content,
                    },
                    {
                        "id": "execution_lifecycle",
                        "state": self._aggregate_read_state(
                            [data["executions"]], has_rows=bool(execution_rows)
                        ),
                        "content": {
                            "records": exec_items,
                            "truncated": data["executions"].truncated,
                        },
                    },
                    {
                        "id": "risk_and_contagion",
                        "state": self._aggregate_read_state(
                            [data["risk_signals"]], has_rows=bool(risk_rows)
                        ),
                        "content": {
                            "riskSignals": risk_items,
                            "riskAssessment": "not_computed",
                            "contagionState": "unknown",
                            "reason": "contagion requires risk/social/relationship authority projections",
                        },
                    },
                ],
                "identityAndAuthorityTemporalSemantics": "current repository state; not reconstructed at the requested event time",
                "unsupportedSlots": self._unsupported_slots(),
            },
            warnings=self._warnings(data, scope_mismatch, evidence_rows_missing),
        )

        timeline_reads = [data[name] for name in ("executions", "activities", "tools")]
        timeline_reads.append(data["communications"])
        timeline_incomplete = any(
            not read.available or read.truncated or read.scope_mismatch for read in timeline_reads
        )
        timeline_state = (
            "degraded"
            if historical_unavailable
            or invalid_window
            or timeline_incomplete
            or not any_sources_available
            else "available"
            if timeline_items
            else "empty"
            if all(
                data[name].available
                for name in ("executions", "activities", "tools", "communications")
            )
            else "unknown"
        )
        timeline_section = ProjectionSection(
            id="timeline",
            state=timeline_state,  # type: ignore[arg-type]
            title="Observed execution and agent activity timeline",
            content={
                "entries": timeline_items,
                "count": len(timeline_items)
                if not any(
                    data[name].truncated or data[name].scope_mismatch
                    for name in ("executions", "activities", "tools", "communications")
                )
                else None,
                "order": "event_timestamp_ascending",
                "causalRelationsDeclared": False,
                "timeMode": request.temporalMode or "window",
                "timeSemantics": (
                    "historical_replay_unavailable"
                    if historical_unavailable
                    else "invalid_window"
                    if invalid_window
                    else "event_time_window"
                    if request.timeRange
                    else "current_bounded_repository_read"
                ),
                "undatedRowsOmittedFromBoundedWindow": temporal_omitted or None,
                "truncated": any(
                    data[name].truncated
                    for name in ("executions", "activities", "tools", "communications")
                ),
                "reason": (
                    "agent execution repositories do not expose bitemporal replay"
                    if historical_unavailable
                    else "time range must contain timezone-aware ISO-8601 bounds"
                    if invalid_window
                    else None
                ),
            },
            warnings=self._warnings(data, scope_mismatch, evidence_rows_missing),
        )

        evidence_section = ProjectionSection(
            id="evidence",
            state=(
                "degraded"
                if incomplete_reads or scope_mismatch
                else "available"
                if evidence_refs
                else "empty"
                if all_sources_available and not evidence_rows_missing
                else "unknown"
                if any_sources_available
                else "degraded"
            ),  # type: ignore[arg-type]
            title="Agent source evidence",
            content={
                "count": None if incomplete_reads or scope_mismatch else len(evidence_refs),
                "evidence": [ref.model_dump(mode="json") for ref in evidence_refs],
                "evidenceMissingRows": evidence_rows_missing or None,
                "sourceStates": source_states,
                "sourceProvenance": agentic_provenance_content,
            },
            warnings=self._warnings(data, scope_mismatch, evidence_rows_missing),
        )

        interaction_items = [{"kind": "observed_activity", **item} for item in activity_items] + [
            {"kind": "observed_tool_invocation", **item} for item in tool_items
        ]
        interaction_items.extend(self._execution_interactions(timeline_exec.rows[:limit]))
        interaction_items.extend(
            {"kind": "agent_message_observation", **item} for item in communication_items
        )
        interaction_reads = [
            data[name] for name in ("activities", "tools", "executions", "communications")
        ]
        interaction_incomplete = any(
            not read.available or read.truncated for read in interaction_reads
        )
        interaction_scope_mismatch = any(read.scope_mismatch for read in interaction_reads)
        interaction_state = (
            "degraded"
            if interaction_scope_mismatch or (interaction_items and interaction_incomplete)
            else "available"
            if interaction_items
            else "empty"
            if data["activities"].available
            and data["tools"].available
            and data["executions"].available
            and data["communications"].available
            else "unknown"
            if any_sources_available
            else "degraded"
        )
        interactions_section = ProjectionSection(
            id="interactions",
            state=interaction_state,  # type: ignore[arg-type]
            title="Observed actions and tool activity",
            content={
                "items": interaction_items,
                "communications": {
                    "state": self._aggregate_read_state(
                        [data["communications"]], has_rows=bool(communication_items)
                    ),
                    "messages": communication_items,
                    "count": self._count(
                        data["communications"], timeline_communications.rows
                    ),
                    "truncated": data["communications"].truncated,
                    "binding": "exact_tenant_inbox_agent_id_to_observed_message",
                    "temporalSemantics": (
                        "message_observation_event_time_window; inbox_agent_binding_is_an_observed_source_reference_without_historical_ownership_replay"
                        if request.timeRange is not None
                        else "current_bounded_observation_read; inbox_agent_binding_is_an_observed_source_reference"
                    ),
                    "contentPolicy": "metadata_only; addresses_subjects_and_message_bodies_omitted",
                    "reason": (
                        "agent messages are observed through exact tenant inbox agent_id references; this does not resolve a canonical Agent and is not a complete provider communication history"
                        if communication_items
                        else "no linked agent message observation was admitted by the requested event-time window"
                        if request.timeRange is not None
                        else "no observed agent messages are linked through tenant-scoped inbox records"
                    ),
                },
                "resources": {
                    "state": "partial",
                    "reason": "resource names are shown only when present in execution policy logs",
                },
                "truncated": any(
                    data[name].truncated
                    for name in ("activities", "tools", "executions", "communications")
                ),
                "unsupportedSlots": [
                    "communications: provider-spine completeness and message bodies are not available from observed agent message records",
                    "social_context: no subject-bound social projection in this provider",
                ],
            },
            warnings=self._warnings(data, scope_mismatch, evidence_rows_missing),
        )

        outcome_dep = self._dependency_state(context, "outcome360")
        outcomes_section = ProjectionSection(
            id="outcomes",
            state="unknown",  # type: ignore[arg-type]
            title="Measured business outcomes",
            content={
                "state": "unknown",
                "outcomeProjectionState": outcome_dep,
                "measuredOutcomeAuthority": {
                    "projection": "outcome360",
                    "dependencyState": outcome_dep,
                    "factState": "unknown",
                    "subject": {
                        "tenantId": tenant_id,
                        "kind": "agent",
                        "id": resolved_canonical_actor,
                        "bindingState": (
                            "resolved" if resolved_canonical_actor is not None else "unknown"
                        ),
                        "evidenceRefs": actor_identity_refs,
                    },
                    "readByAgent360": False,
                },
                "sourceReportedEvidence": {
                    "state": "not_used_for_measurement",
                    "fields": [
                        "agent_outcome_recorded",
                        "execution_status",
                        "outcome_ref",
                        "caller_actor_type",
                    ],
                    "reason": (
                        "agent callbacks, execution status, opaque outcome references, and "
                        "caller-supplied actor types are source assertions; they do not "
                        "establish a measured business outcome or value attribution"
                    ),
                },
                "reason": (
                    "execution status is not a business outcome; this provider reads no "
                    "measured outcome fact, and Outcome360 must match a durable fact to "
                    "the exact tenant and canonical Agent subject"
                ),
                "claims": [],
            },
            warnings=[
                "measured outcomes are delegated to outcome360; no causal or success inference is made"
            ],
        )

        claims = (
            []
            if invalid_window
            else self._claims(
                request=request,
                principal_identity_by_user_id=execution_principal_identity[
                    "resolvedByPrincipal"
                ],
                config=config if request.timeRange is None else None,
                config_ref=config_ref if request.timeRange is None else None,
                agent_identity_rows=(
                    actor_identity_rows if resolved_canonical_actor is not None else []
                ),
                execution_rows=timeline_exec.rows,
                delegation_records=delegation_records if request.timeRange is None else [],
                delegation_party_identity_views=delegation_party_views,
                active_delegation_conflicts=(
                    list(active_delegation_conflicts.values()) if request.timeRange is None else []
                ),
                activity_rows=timeline_activity.rows,
                tool_rows=timeline_tools.rows,
                risk_rows=timeline_risks.rows,
                communication_rows=timeline_communications.rows,
            )
        )
        if claim_evidence_refs:
            claims.append(
                ClaimEnvelope(
                    id=f"agent360:validated-evidence-trace:{agent_id}",
                    kind="agent360_validated_evidence_trace",
                    subject=request.subject,
                    evidenceRefs=claim_evidence_refs[:MAX_READ_LIMIT],
                    claims=[
                        "Tenant-scoped Agent360 source rows contributed the cited stable evidence references. Canonical Bronze lineage is included only for exact joined records; the bounded trace does not establish complete source coverage, verified source identity, freshness, or an authorization decision."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["evidence_trace"],
                )
            )
        capability_access_refs: list[EvidenceRef] = []
        for raw_ref in capability_access_profile_view.get("evidenceRefs", []):
            try:
                capability_access_refs.append(EvidenceRef.model_validate(raw_ref))
            except Exception:  # noqa: BLE001 - malformed authority evidence is omitted
                continue
        if (
            not invalid_window
            and capability_access_profile_view.get("state") == "available"
            and capability_access_refs
        ):
            claims.append(
                ClaimEnvelope(
                    id="capability_access_profile",
                    kind="agent_capability_access_profile",
                    subject=request.subject,
                    evidenceRefs=_dedupe_refs(capability_access_refs),
                    claims=[
                        "Tenant-scoped capability reach is joined to exact active invoke-grant records for the resolved canonical Agent and reflects current repository state at read time; it does not evaluate authorization for a new action or resource."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["capabilities"],
                )
            )
        policy_boundary_claims = [
            claim
            for claim in claims
            if claim.kind == "server_recorded_delegation_decision"
            and "policy_boundary" in (claim.domainSlotIds or [])
        ]
        execution_read = data["executions"]
        policy_boundary_warnings = ["standing_policy_boundary_not_exposed"]
        if execution_read.truncated:
            policy_boundary_warnings.append("action_scoped_policy_decision_read_truncated")
        if execution_read.scope_mismatch or not execution_read.scope_known:
            policy_boundary_warnings.append("action_scoped_policy_decision_read_scope_incomplete")
        if invalid_window:
            policy_boundary_warnings.append("action_scoped_policy_decision_window_invalid")
        if policy_boundary_claims:
            policy_boundary_section = ProjectionSection(
                id="policy_boundary",
                state="degraded",
                title="Observed action-scoped policy decisions",
                content={
                    "state": "partial",
                    "effectivePolicyState": "unknown",
                    "decisionScope": "historical_action_scoped_only",
                    "decisions": [
                        claim.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for claim in policy_boundary_claims
                    ],
                    "limitations": [
                        "A recorded decision is evidence about one request at its recorded time; it does not establish standing policy or current authorization."
                    ],
                },
                warnings=policy_boundary_warnings,
                canonicalAuthorityRefs=["agent_executions"],
            )
        elif not execution_read.available:
            policy_boundary_section = ProjectionSection(
                id="policy_boundary",
                state="degraded",
                title="Policy boundary evidence unavailable",
                content=None,
                warnings=["action_scoped_policy_decision_source_unavailable"],
                canonicalAuthorityRefs=["agent_executions"],
            )
        elif (
            execution_read.truncated
            or execution_read.scope_mismatch
            or not execution_read.scope_known
            or invalid_window
        ):
            policy_boundary_section = ProjectionSection(
                id="policy_boundary",
                state="degraded",
                title="Policy boundary evidence is incomplete",
                content=None,
                warnings=policy_boundary_warnings,
                canonicalAuthorityRefs=["agent_executions"],
            )
        else:
            policy_boundary_section = ProjectionSection(
                id="policy_boundary",
                state="unknown",
                title="Policy boundary not established",
                content=None,
                warnings=["standing_policy_boundary_not_exposed"],
                canonicalAuthorityRefs=["agent_executions"],
            )
        sections = [
            summary_section,
            state_section,
            timeline_section,
            evidence_section,
            interactions_section,
            outcomes_section,
            policy_boundary_section,
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims if request.includeClaims is not False else [],
            dependencyState=list(context.dependencyState),
            asOf=None,
            generatedAt=_utc_now_iso(),
            degradedReasons=sorted(set(degraded_reasons)),
            temporalMode=request.temporalMode or "window",
            lensIds=request.lensIds,
        )

    async def _safe_read(self, name: str, loader: Any, limit: int) -> _Read:
        try:
            value = await loader()
            batch_truncated = False
            batch_scope_mismatch = False
            batch_scope_known = True
            if isinstance(value, Agent360ReadBatch):
                batch_truncated = value.truncated
                batch_scope_mismatch = value.scope_mismatch
                batch_scope_known = value.scope_known
                value = value.rows
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                return _Read(rows=None, available=False)
            truncated = batch_truncated or len(value) > limit
            return _Read(
                rows=value[:limit],
                available=True,
                truncated=truncated,
                scope_mismatch=batch_scope_mismatch,
                scope_known=batch_scope_known,
            )
        except Exception:  # fail-isolate with a content-free source state
            return _Read(rows=None, available=False)

    @staticmethod
    def _reason_for(name: str) -> str:
        return {
            "config": REASON_CONFIG_UNAVAILABLE,
            "actor_identity": "agent_identity_binding_source_unavailable",
            "principal_identities": "agent_principal_identity_source_unavailable",
            "executions": REASON_EXECUTION_UNAVAILABLE,
            "incoming_delegations": REASON_DELEGATION_UNAVAILABLE,
            "outgoing_delegations": REASON_DELEGATION_UNAVAILABLE,
            "active_delegations": REASON_DELEGATION_UNAVAILABLE,
            "activities": REASON_ACTIVITY_UNAVAILABLE,
            "tools": REASON_TOOL_UNAVAILABLE,
            "capability_access_profile": "agent_capability_access_profile_unavailable",
            "risk_signals": REASON_RISK_UNAVAILABLE,
            "communications": REASON_COMMUNICATION_UNAVAILABLE,
        }.get(name, "agent_source_unavailable")

    @staticmethod
    def _tenant_agent_rows(
        read: _Read, tenant_id: str, agent_id: str
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], False
        rows: list[dict[str, Any]] = []
        mismatch = False
        for row in read.rows:
            if row.get("tenant_id") != tenant_id:
                mismatch = True
                continue
            if row.get("agent_id") != agent_id:
                # A source query is not enough when the stored row cannot bind
                # itself back to the requested agent. Omit rather than infer.
                mismatch = True
                continue
            rows.append(row)
        return rows, mismatch

    @staticmethod
    def _tenant_agent_identity(
        read: _Read, tenant_id: str, agent_id: str
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], read.scope_mismatch
        rows: list[dict[str, Any]] = []
        mismatch = read.scope_mismatch
        for row in read.rows:
            if (
                row.get("tenant_id") != tenant_id
                or row.get("agent_id") != agent_id
                or not _first(row, "canonical_agent_entity_id")
                or not _first(row, "identity_evidence_id")
                or not _first(row, "identity_evidence_source")
            ):
                mismatch = True
                continue
            rows.append(row)
        return rows, mismatch

    @staticmethod
    def _tenant_principal_identity_rows(
        read: _Read, tenant_id: str, principal_user_ids: set[str]
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], read.scope_mismatch
        rows: list[dict[str, Any]] = []
        mismatch = read.scope_mismatch
        for row in read.rows:
            principal_id = _first(row, "principal_user_id")
            canonical_id = _first(row, "canonical_human_entity_id")
            evidence_refs = row.get("identity_evidence_refs")
            normalized_refs: list[dict[str, Any]] = []
            ref_sources: set[str] = set()
            if isinstance(evidence_refs, list):
                for raw_ref in evidence_refs:
                    try:
                        evidence_ref = EvidenceRef.model_validate(raw_ref)
                        if (
                            evidence_ref.source not in {"identity_aliases", "identity_subjects"}
                            or evidence_ref.type != "entity"
                        ):
                            mismatch = True
                            continue
                        ref_sources.add(evidence_ref.source)
                        normalized_refs.append(evidence_ref.model_dump(mode="json"))
                    except Exception:  # noqa: BLE001 - malformed identity evidence fails closed
                        mismatch = True
            if (
                row.get("tenant_id") != tenant_id
                or principal_id not in principal_user_ids
                or canonical_id is None
                or not normalized_refs
                or ref_sources != {"identity_aliases", "identity_subjects"}
                or len(normalized_refs) != len(evidence_refs or [])
            ):
                mismatch = True
                continue
            rows.append({**row, "identity_evidence_refs": normalized_refs})
        return rows, mismatch

    @staticmethod
    def _tenant_capability_access_profile_rows(
        read: _Read,
        tenant_id: str,
        agent_id: str,
        canonical_agent_entity_id: Optional[str],
    ) -> tuple[list[dict[str, Any]], bool]:
        """Accept only the exact runtime profile and canonical-agent grant read."""
        if not read.available or read.rows is None:
            return [], read.scope_mismatch
        rows: list[dict[str, Any]] = []
        mismatch = read.scope_mismatch
        for row in read.rows:
            not_applicable = row.get("not_applicable") is True
            if (
                row.get("tenant_id") != tenant_id
                or row.get("agent_id") != agent_id
                or (
                    not not_applicable
                    and (
                        not canonical_agent_entity_id
                        or row.get("canonical_agent_entity_id") != canonical_agent_entity_id
                        or not isinstance(row.get("profile"), dict)
                    )
                )
            ):
                mismatch = True
                continue
            profile = row.get("profile")
            if isinstance(profile, dict):
                subject = profile.get("subject")
                if not isinstance(subject, dict) or subject != {"kind": "agent", "id": agent_id}:
                    mismatch = True
                    continue
            rows.append(row)
        if len(rows) > 1:
            mismatch = True
            return [], mismatch
        return rows, mismatch

    @staticmethod
    def _validate_capability_grant_records(
        records: Any,
        tenant_id: Any,
        canonical_agent_entity_id: Any,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Validate canonical grant rows and their invoke scope before projection."""
        from actions.agent_access_intelligence.authority import AUTHORIZATION_KIND

        if (
            not isinstance(records, list)
            or not isinstance(tenant_id, str)
            or not isinstance(canonical_agent_entity_id, str)
        ):
            return [], False
        validated: list[dict[str, Any]] = []
        complete = True
        seen_ids: set[str] = set()
        for row in records:
            if not isinstance(row, dict):
                complete = False
                continue
            record_id = _first(row, "authorization_id", "delegation_id", "id")
            scope = row.get("scope")
            actions = scope.get("actions") if isinstance(scope, dict) else None
            resources = scope.get("resources") if isinstance(scope, dict) else None
            capability_id = row.get("capability_id")
            server_ref = row.get("server_ref")
            expected_resource = (
                f"capability:{capability_id}"
                if isinstance(capability_id, str) and capability_id
                else f"capability-server:{server_ref}"
                if isinstance(server_ref, str) and server_ref
                else None
            )
            exact = bool(
                row.get("tenant_id") == tenant_id
                and row.get("agent_id") == canonical_agent_entity_id
                and row.get("grantee_entity_id") == canonical_agent_entity_id
                and row.get("authorization_kind") == AUTHORIZATION_KIND
                and isinstance(record_id, str)
                and record_id
                and record_id not in seen_ids
                and isinstance(actions, list)
                and actions == ["invoke"]
                and isinstance(resources, list)
                and expected_resource is not None
                and resources == [expected_resource]
                and row.get("state") in {"active", "pending", "revoked", "expired"}
            )
            if not exact:
                complete = False
                continue
            seen_ids.add(record_id)
            validated.append(row)
        return validated, complete

    @staticmethod
    def _capability_profile_complete(
        rows: list[dict[str, Any]],
        read: _Read,
        *,
        scope_mismatch: bool,
    ) -> bool:
        """Whether observed reach and canonical-grant inputs can be counted."""
        if not read.available or read.truncated or scope_mismatch or read.scope_mismatch:
            return False
        if len(rows) != 1 or rows[0].get("not_applicable") is True:
            return False
        row = rows[0]
        profile = row.get("profile")
        if not isinstance(profile, dict):
            return False
        missing = profile.get("missing_inputs")
        if missing is not None and not isinstance(missing, list):
            return False
        missing = [item for item in missing or [] if isinstance(item, str)]
        # The profile's aggregate grant scan is runtime-keyed. Its status does not
        # substitute for, or invalidate, the separate canonical-grantee scan.
        reach_missing = [
            item for item in missing if not item.startswith("capability_authorizations:")
        ]
        profile_known_for_reach = profile.get("profile_known") is True or (
            bool(missing) and not reach_missing
        )
        reach = profile.get("reach")
        identity = profile.get("identity")
        grants = row.get("canonical_grant_records")
        _, grants_valid = Agent360Provider._validate_capability_grant_records(
            grants, row.get("tenant_id"), row.get("canonical_agent_entity_id")
        )
        return bool(
            not reach_missing
            and profile_known_for_reach
            and isinstance(reach, dict)
            and isinstance(reach.get("capabilities"), list)
            and isinstance(identity, dict)
            and isinstance(identity.get("installation_ids"), list)
            and identity.get("installation_ids")
            and row.get("canonical_grant_read_complete") is True
            and grants_valid
        )

    @staticmethod
    def _capability_access_profile_view(
        rows: list[dict[str, Any]],
        read: _Read,
        *,
        scope_mismatch: bool,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Project observed capability reach and invoke-grant coverage without
        turning it into an authorization verdict for an arbitrary new action.
        """
        if not read.available:
            return {
                "state": "unavailable",
                "profileKnown": None,
                "counts": None,
                "capabilities": [],
                "authorization": {"known": False, "activeGrantRecordIds": []},
                "evidenceRefs": [],
                "reason": "capability access profile authority was unavailable",
            }
        if scope_mismatch or read.scope_mismatch:
            return {
                "state": "conflicted",
                "profileKnown": None,
                "counts": None,
                "capabilities": [],
                "authorization": {"known": False, "activeGrantRecordIds": []},
                "evidenceRefs": [],
                "reason": "capability access profile did not match the requested tenant and agent",
            }
        if not rows:
            return {
                "state": "unknown",
                "profileKnown": None,
                "counts": None,
                "capabilities": [],
                "authorization": {"known": False, "activeGrantRecordIds": []},
                "evidenceRefs": [],
                "reason": "no exact capability access profile was returned",
            }
        row = rows[0]
        if row.get("not_applicable") is True:
            return {
                "state": "not_applicable",
                "profileKnown": None,
                "counts": None,
                "capabilities": [],
                "authorization": {"known": False, "activeGrantRecordIds": []},
                "evidenceRefs": [],
                "reason": "capability installations are keyed by runtime agent ID, not entity ID",
            }
        profile = row.get("profile")
        if not isinstance(profile, dict):
            return {
                "state": "unknown",
                "profileKnown": False,
                "counts": None,
                "capabilities": [],
                "authorization": {"known": False, "activeGrantRecordIds": []},
                "evidenceRefs": [],
                "reason": "capability access profile returned no profile object",
            }

        missing_inputs = profile.get("missing_inputs")
        if not isinstance(missing_inputs, list):
            missing_inputs = []
        missing_inputs = [item for item in missing_inputs if isinstance(item, str)]
        reach_missing = [
            item for item in missing_inputs if not item.startswith("capability_authorizations:")
        ]
        profile_known_for_reach = profile.get("profile_known") is True or (
            bool(missing_inputs) and not reach_missing
        )

        reach = profile.get("reach")
        reach = reach if isinstance(reach, dict) else {}
        raw_capabilities = reach.get("capabilities")
        capabilities = [
            {
                "capabilityId": item.get("capability_id"),
                "serverKey": item.get("server_key"),
                "provider": item.get("provider"),
                "toolName": item.get("tool_name"),
                "basis": item.get("basis"),
                "invokeGrantCoversCapability": None,
                "activeGrantRecordIds": [],
            }
            for item in raw_capabilities
            if isinstance(item, dict) and isinstance(item.get("capability_id"), str)
        ] if isinstance(raw_capabilities, list) else []

        canonical_agent_entity_id = row.get("canonical_agent_entity_id")
        grant_rows, grant_rows_valid = Agent360Provider._validate_capability_grant_records(
            row.get("canonical_grant_records"),
            tenant_id,
            canonical_agent_entity_id,
        )
        grant_read_complete = bool(
            row.get("canonical_grant_read_complete") is True
            and not read.truncated
            and grant_rows_valid
        )
        active_grants = [grant for grant in grant_rows if grant.get("state") == "active"]
        from actions.agent_access_intelligence.authority import server_ref_for

        for capability in capabilities:
            server_key = capability.get("serverKey")
            server_ref = (
                server_ref_for(tenant_id, server_key)
                if isinstance(server_key, str) and server_key
                else None
            )
            matching = [
                grant
                for grant in active_grants
                if grant.get("capability_id") == capability["capabilityId"]
                or (server_ref is not None and grant.get("server_ref") == server_ref)
            ]
            capability["invokeGrantCoversCapability"] = (
                bool(matching) if grant_read_complete else None
            )
            capability["activeGrantRecordIds"] = [
                record_id
                for grant in matching[:MAX_READ_LIMIT]
                if isinstance(
                    (record_id := _first(grant, "authorization_id", "delegation_id", "id")),
                    str,
                )
            ]
            capability["activeGrantRecordIdsTruncated"] = len(matching) > MAX_READ_LIMIT

        evidence_refs: list[dict[str, Any]] = []
        identity = profile.get("identity")
        identity = identity if isinstance(identity, dict) else {}
        observation = profile.get("observation")
        observation = observation if isinstance(observation, dict) else {}
        last_seen_at = observation.get("last_seen_at")
        for installation_id in identity.get("installation_ids", []):
            if isinstance(installation_id, str) and installation_id:
                evidence_refs.append(
                    EvidenceRef(
                        id=installation_id,
                        type="event",
                        source="capability_installations",
                        observedAt=last_seen_at if isinstance(last_seen_at, str) else None,
                    ).model_dump(mode="json", exclude_none=True)
                )
        for item in capabilities:
            evidence_refs.append(
                EvidenceRef(
                    id=item["capabilityId"],
                    type="entity",
                    source="capability_catalog",
                ).model_dump(mode="json", exclude_none=True)
            )
        active_record_ids = [
            record_id
            for grant in active_grants
            if isinstance(
                (record_id := _first(grant, "authorization_id", "delegation_id", "id")),
                str,
            )
        ]
        visible_active_records = active_grants[:MAX_READ_LIMIT] if grant_read_complete else []
        for grant in visible_active_records:
            evidence_refs.append(
                EvidenceRef(
                    id=_first(grant, "authorization_id", "delegation_id", "id"),
                    type="relationship",
                    source="delegations",
                    observedAt=_first(grant, "created_at", "starts_at"),
                ).model_dump(mode="json", exclude_none=True)
            )

        installation_ids = identity.get("installation_ids")
        reach_complete = bool(
            not reach_missing
            and profile_known_for_reach
            and isinstance(installation_ids, list)
            and installation_ids
            and isinstance(raw_capabilities, list)
        )
        complete = reach_complete and grant_read_complete
        state = (
            "available"
            if complete
            else "partial"
            if reach_complete
            or isinstance(raw_capabilities, list)
            or isinstance(row.get("canonical_grant_records"), list)
            else "unknown"
        )
        servers = identity.get("servers_observed")
        invoked_count = sum(1 for item in capabilities if item.get("basis") == "invoked")
        covered_count = sum(
            1 for item in capabilities if item.get("invokeGrantCoversCapability") is True
        )
        uncovered_count = sum(
            1 for item in capabilities if item.get("invokeGrantCoversCapability") is False
        )
        counts = (
            {
                "servers_observed": len(servers) if isinstance(servers, list) else None,
                "capabilities_reachable": len(capabilities),
                "capabilities_invoked": invoked_count,
                "capabilities_authorized": covered_count,
                "capabilities_unauthorized": uncovered_count,
                "authorizations_active": len(active_grants),
            }
            if complete
            else None
        )
        last_observed_at = observation.get("last_seen_at")
        visible_active_record_ids = active_record_ids[:MAX_READ_LIMIT] if grant_read_complete else []

        return {
            "state": state,
            "profileKnown": complete,
            "basis": profile.get("basis") or "observed_only",
            "counts": counts,
            "capabilities": capabilities,
            "authorization": {
                "known": grant_read_complete,
                "canonicalAgentEntityId": canonical_agent_entity_id,
                "activeGrantCount": len(active_grants) if grant_read_complete else None,
                "activeGrantRecordIds": visible_active_record_ids,
                "activeGrantRecordIdsTruncated": (
                    read.truncated or len(active_record_ids) > MAX_READ_LIMIT
                ),
                "activeGrantRecords": [
                    {
                        "recordId": _first(grant, "authorization_id", "delegation_id", "id"),
                        "state": grant.get("state"),
                        "capabilityId": grant.get("capability_id"),
                        "serverRef": grant.get("server_ref"),
                        "action": "invoke",
                        "evidenceRef": {
                            "id": _first(grant, "authorization_id", "delegation_id", "id"),
                            "type": "relationship",
                            "source": "delegations",
                            **(
                                {"observedAt": _first(grant, "created_at", "starts_at")}
                                if _first(grant, "created_at", "starts_at")
                                else {}
                            ),
                        },
                    }
                    for grant in visible_active_records
                ],
                "action": "invoke",
                "effectiveAuthorizationDecision": "unknown",
                "reason": (
                    "active capability grants describe observed invoke-scope coverage; "
                    "they do not evaluate a new action/resource request"
                ),
            },
            "missingInputs": (
                reach_missing
                + ([] if grant_read_complete else ["canonical_capability_grant_read_incomplete"])
            ),
            "evidenceRefs": _dedupe_json_refs(evidence_refs),
            "freshnessSemantics": "current_repository_state; active grant state is derived at read time; no historical replay",
            "lastObservedAt": last_observed_at if isinstance(last_observed_at, str) else None,
            "reason": None if complete else "exact canonical reach or grant evidence is incomplete",
        }

    @staticmethod
    def _resolve_execution_principal_identity(
        principals: dict[str, Any],
        *,
        read: _Read,
        identity_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve principals only when every bounded tenant lookup is complete."""
        by_principal: dict[str, dict[str, Any]] = {}
        for row in identity_rows:
            principal_id = _first(row, "principal_user_id")
            canonical_id = _first(row, "canonical_human_entity_id")
            if principal_id is None or canonical_id is None:
                continue
            candidate = by_principal.setdefault(
                principal_id,
                {"canonicalHumanEntityIds": set(), "evidenceRefs": []},
            )
            candidate["canonicalHumanEntityIds"].add(canonical_id)
            candidate["evidenceRefs"].extend(row.get("identity_evidence_refs", []))

        principal_ids = {
            _first(candidate.get("principal", {}), "id")
            for candidate in principals.get("candidates", [])
            if isinstance(candidate, dict) and isinstance(candidate.get("principal"), dict)
        }
        principal_ids.discard(None)
        evidence_refs = _dedupe_json_refs(
            [
                ref
                for principal_id in principal_ids
                for ref in by_principal.get(principal_id, {}).get("evidenceRefs", [])
            ]
        )
        complete = read.available and not read.truncated and not read.scope_mismatch and read.scope_known
        per_principal_ids = {
            principal_id: by_principal.get(principal_id, {}).get("canonicalHumanEntityIds", set())
            for principal_id in principal_ids
        }
        all_canonical_ids = {
            canonical_id
            for canonical_ids in per_principal_ids.values()
            for canonical_id in canonical_ids
        }
        if not principal_ids:
            state = "unknown"
            canonical_id = None
            reason = "no_authenticated_execution_principal_was_observed"
        elif not read.available:
            state = "unavailable"
            canonical_id = None
            reason = "tenant human identity authority could not be read"
        elif read.scope_mismatch:
            state = "conflicted"
            canonical_id = None
            reason = "principal identity rows did not match their tenant or subject scope"
        elif read.truncated or not read.scope_known:
            state = "partial"
            canonical_id = None
            reason = "the bounded principal identity read was incomplete"
        elif any(len(canonical_ids) > 1 for canonical_ids in per_principal_ids.values()):
            state = "ambiguous"
            canonical_id = None
            reason = "an authenticated principal resolves to multiple canonical human entities"
        elif len(all_canonical_ids) > 1:
            state = "ambiguous"
            canonical_id = None
            reason = "observed executions were initiated by multiple canonical human entities"
        elif any(not canonical_ids for canonical_ids in per_principal_ids.values()):
            state = "unresolved"
            canonical_id = None
            reason = "no active tenant USER_ID alias resolved every observed principal"
        elif complete and len(all_canonical_ids) == 1:
            state = "resolved"
            canonical_id = next(iter(all_canonical_ids))
            reason = None
        else:
            state = "unknown"
            canonical_id = None
            reason = "canonical human identity could not be established"

        enriched_candidates: list[dict[str, Any]] = []
        for candidate in principals.get("candidates", []):
            principal = candidate.get("principal") if isinstance(candidate, dict) else None
            principal_id = _first(principal, "id") if isinstance(principal, dict) else None
            canonical_ids = per_principal_ids.get(principal_id or "", set())
            candidate_identity_state = (
                "ambiguous"
                if len(canonical_ids) > 1
                else "resolved"
                if complete and len(canonical_ids) == 1
                else "unresolved"
                if complete and not canonical_ids
                else "partial"
                if read.truncated or not read.scope_known
                else "unavailable"
                if not read.available
                else "conflicted"
                if read.scope_mismatch
                else "unknown"
            )
            enriched_candidates.append(
                {
                    **candidate,
                    "canonicalHumanEntityId": (
                        next(iter(canonical_ids))
                        if candidate_identity_state == "resolved"
                        else None
                    ),
                    "canonicalIdentityState": candidate_identity_state,
                    "canonicalIdentityEvidenceRefs": _dedupe_json_refs(
                        by_principal.get(principal_id or "", {}).get("evidenceRefs", [])
                    ),
                }
            )

        return {
            "canonicalIdentity": {
                "state": state,
                "canonicalHumanEntityId": canonical_id,
                "candidateEntityIds": sorted(all_canonical_ids),
                "evidenceRefs": evidence_refs,
                "reason": reason,
            },
            "evidenceRefs": evidence_refs,
            "resolvedByPrincipal": {
                principal_id: {
                    "canonicalHumanEntityId": next(iter(canonical_ids)),
                    "evidenceRefs": _dedupe_json_refs(
                        by_principal.get(principal_id, {}).get("evidenceRefs", [])
                    ),
                }
                for principal_id, canonical_ids in per_principal_ids.items()
                if complete and len(canonical_ids) == 1
            },
            "candidates": enriched_candidates,
        }

    @staticmethod
    def _tenant_agent_communications(
        read: _Read, tenant_id: str, agent_id: str
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], read.scope_mismatch
        rows: list[dict[str, Any]] = []
        mismatch = read.scope_mismatch
        for row in read.rows:
            inbox_id = _first(row, "inbox_obs_id")
            try:
                inbox_ref = EvidenceRef.model_validate(row.get("inbox_evidence_ref"))
            except Exception:  # noqa: BLE001 - missing join evidence fails closed
                mismatch = True
                continue
            if (
                row.get("tenant_id") != tenant_id
                or row.get("agent_id") != agent_id
                or row.get("subject_binding_basis") != "exact_tenant_inbox_agent_id"
                or not inbox_id
                or inbox_ref.source != "obs_agent_inboxes"
                or inbox_ref.id != inbox_id
                or inbox_ref.type != "event"
            ):
                mismatch = True
                continue
            rows.append(row)
        return rows, mismatch

    @staticmethod
    def _tenant_delegation_rows(
        read: _Read, tenant_id: str, agent_id: str, party_field: str
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], False
        rows: list[dict[str, Any]] = []
        mismatch = False
        for row in read.rows:
            if row.get("tenant_id") != tenant_id or row.get(party_field) != agent_id:
                mismatch = True
                continue
            rows.append(row)
        return rows, mismatch

    @staticmethod
    def _tenant_delegation_party_identity_rows(
        read: _Read, tenant_id: str, requested_entity_ids: set[str]
    ) -> tuple[list[dict[str, Any]], bool]:
        if not read.available or read.rows is None:
            return [], read.scope_mismatch
        rows: list[dict[str, Any]] = []
        mismatch = read.scope_mismatch
        for row in read.rows:
            entity_id = _first(row, "party_entity_id")
            if (
                row.get("tenant_id") != tenant_id
                or entity_id not in requested_entity_ids
                or row.get("identity_evidence_source") != "entities"
                or _first(row, "identity_evidence_id") != entity_id
            ):
                mismatch = True
                continue
            rows.append(row)
        return rows, mismatch

    @classmethod
    def _delegation_party_identity_view(
        cls,
        entity_id: Optional[str],
        *,
        read: _Read,
        identity_rows_by_id: dict[str, list[dict[str, Any]]],
        delegation_evidence_ref: Optional[EvidenceRef],
    ) -> dict[str, Any]:
        evidence_refs = (
            [delegation_evidence_ref.model_dump(mode="json")]
            if delegation_evidence_ref is not None
            else []
        )
        if entity_id is None:
            return {
                "state": "unknown",
                "party": None,
                "evidenceRefs": evidence_refs,
                "reason": "delegation record does not contain a party entity ID",
            }

        matches = identity_rows_by_id.get(entity_id, [])
        party_refs = [
            ref.model_dump(mode="json")
            for row in matches
            if (
                ref := cls._ref_one(
                    row,
                    "entities",
                    ("identity_evidence_id",),
                    ("identity_observed_at",),
                )
            )
        ]
        evidence_refs = _dedupe_json_refs([*evidence_refs, *party_refs])
        if not read.available or not read.scope_known or read.truncated or read.scope_mismatch:
            return {
                "state": "unknown",
                "party": None,
                "evidenceRefs": evidence_refs,
                "reason": "tenant-scoped entity identity read is incomplete",
            }
        if len(matches) > 1:
            return {
                "state": "conflicted",
                "party": None,
                "evidenceRefs": evidence_refs,
                "reason": "multiple tenant-scoped entity rows matched this party ID",
            }
        if not matches:
            return {
                "state": "unknown",
                "party": None,
                "evidenceRefs": evidence_refs,
                "reason": "no tenant-scoped canonical entity row resolved this party ID",
            }

        entity_type = _first(matches[0], "party_entity_type")
        actor_kind = {
            "agent": "agent",
            "human": "human",
            "organization": "org",
            "system": "system",
        }.get(entity_type or "")
        if actor_kind is None:
            return {
                "state": "unknown",
                "party": None,
                "evidenceRefs": evidence_refs,
                "reason": "tenant-scoped entity type is not a supported actor kind",
            }
        party = Experience360ActorParty(kind=actor_kind, id=entity_id)
        return {
            "state": "resolved",
            "party": party.model_dump(mode="json", exclude_none=True),
            "evidenceRefs": evidence_refs,
            "reason": None,
        }

    @staticmethod
    def _read_state(read: _Read) -> str:
        if not read.available:
            return "unavailable"
        if not read.scope_known:
            return "unknown"
        if read.scope_mismatch:
            return "degraded"
        if read.truncated:
            return "truncated"
        return "available"

    @staticmethod
    def _aggregate_read_state(reads: list[_Read], *, has_rows: bool) -> str:
        if any(not read.available for read in reads):
            return "degraded" if any(read.available for read in reads) else "unknown"
        if any(read.truncated or read.scope_mismatch for read in reads):
            return "degraded"
        if any(not read.scope_known for read in reads):
            return "degraded" if has_rows else "unknown"
        return "available" if has_rows else "empty"

    @staticmethod
    def _count(read: _Read, rows: list[Any]) -> Optional[int]:
        if not read.available or read.truncated or read.scope_mismatch or not read.scope_known:
            return None
        return len(rows)

    @staticmethod
    def _warnings(
        data: dict[str, _Read], scope_mismatch: bool, evidence_missing: int
    ) -> Optional[list[str]]:
        warnings = [f"{name}_read_unavailable" for name, read in data.items() if not read.available]
        warnings.extend(f"{name}_read_truncated" for name, read in data.items() if read.truncated)
        warnings.extend(
            f"{name}_scope_mismatch" for name, read in data.items() if read.scope_mismatch
        )
        warnings.extend(
            f"{name}_scope_unknown" for name, read in data.items() if not read.scope_known
        )
        if scope_mismatch:
            warnings.append("cross_scope_rows_omitted")
        if evidence_missing:
            warnings.append("rows_without_stable_evidence_id_omitted_from_claims")
        return warnings or None

    @staticmethod
    def _ref_one(
        row: Optional[dict[str, Any]],
        source: str,
        id_keys: tuple[str, ...],
        time_keys: tuple[str, ...],
    ) -> Optional[EvidenceRef]:
        return (
            _evidence_ref(row, source=source, id_keys=id_keys, time_keys=time_keys) if row else None
        )

    @classmethod
    def _collect_evidence(
        cls,
        *,
        config_rows: list[dict[str, Any]],
        agent_identities: list[dict[str, Any]],
        principal_identities: list[dict[str, Any]],
        executions: list[dict[str, Any]],
        delegations: list[tuple[dict[str, Any], str, bool]],
        delegation_party_identities: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        communications: list[dict[str, Any]],
    ) -> tuple[list[EvidenceRef], int]:
        refs: list[EvidenceRef] = []
        rows_missing = 0
        groups = (
            (config_rows, "agent_configs", ("agent_id",), ("created_at",)),
            (executions, "agent_executions", ("execution_id", "id"), ("started_at", "created_at")),
            (
                [row for row, _, _ in delegations],
                "delegations",
                ("delegation_id", "id"),
                ("starts_at",),
            ),
            (
                activities,
                "obs_agent_activities",
                ("observation_id", "activity_id", "id"),
                ("observed_at", "occurred_at"),
            ),
            (
                tools,
                "obs_agent_tools",
                ("invocation_id", "tool_id", "id"),
                ("observed_at", "occurred_at"),
            ),
            (risks, "obs_agent_risk_signals", ("signal_id", "id"), ("detected_at", "observed_at")),
            (
                communications,
                "obs_agent_messages",
                ("message_obs_id", "id"),
                ("observed_at", "received_at"),
            ),
        )
        for rows, source, id_keys, time_keys in groups:
            for row in rows:
                ref = _evidence_ref(row, source=source, id_keys=id_keys, time_keys=time_keys)
                if ref is None:
                    rows_missing += 1
                else:
                    refs.append(ref)
        for row in communications:
            try:
                inbox_ref = EvidenceRef.model_validate(row.get("inbox_evidence_ref"))
            except Exception:  # noqa: BLE001 - malformed binding evidence is omitted
                rows_missing += 1
                continue
            refs.append(inbox_ref)
        for row in agent_identities:
            source = _first(row, "identity_evidence_source")
            ref = (
                _evidence_ref(
                    row,
                    source=source,
                    id_keys=("identity_evidence_id",),
                    time_keys=("identity_bound_at",),
                )
                if source
                else None
            )
            if ref is None:
                rows_missing += 1
            else:
                refs.append(ref)
        for row in delegation_party_identities:
            ref = _evidence_ref(
                row,
                source="entities",
                id_keys=("identity_evidence_id",),
                time_keys=("identity_observed_at",),
            )
            if ref is None:
                rows_missing += 1
            else:
                refs.append(ref)
        for row in principal_identities:
            raw_refs = row.get("identity_evidence_refs")
            if not isinstance(raw_refs, list) or not raw_refs:
                rows_missing += 1
                continue
            for raw_ref in raw_refs:
                try:
                    refs.append(EvidenceRef.model_validate(raw_ref))
                except Exception:  # noqa: BLE001 - malformed identity evidence is omitted
                    rows_missing += 1
        return _dedupe_refs(refs), rows_missing

    def _execution_view(self, row: dict[str, Any]) -> dict[str, Any]:
        ref = self._ref_one(
            row, "agent_executions", ("execution_id", "id"), ("started_at", "created_at")
        )
        return {
            "executionId": _first(row, "execution_id", "id"),
            "status": _first(row, "status"),
            "startedAt": _first(row, "started_at", "created_at"),
            "endedAt": _first(row, "ended_at"),
            "delegationId": _first(row, "delegation_id"),
            "triggeredByEventId": _first(row, "triggered_by_event_id"),
            "initiatingPrincipalUserId": _first(row, "initiating_principal_user_id"),
            "evidenceRef": ref.model_dump(mode="json") if ref else None,
        }

    def _recorded_execution_decision(
        self,
        row: dict[str, Any],
        *,
        canonical_delegations: dict[str, dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        policy_log = row.get("policy_log") if isinstance(row.get("policy_log"), dict) else {}
        decision = policy_log.get("delegation_check")
        if not isinstance(decision, dict) or not isinstance(decision.get("allowed"), bool):
            return None
        evidence = self._ref_one(
            row, "agent_executions", ("execution_id", "id"), ("started_at", "created_at")
        )
        execution_id = _first(row, "execution_id", "id")
        if evidence is None or execution_id is None:
            return None
        snapshot = row.get("input_snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        asserted_delegation_id = _first(row, "delegation_id")
        decision_delegation_id = _first(decision, "delegation_id")
        delegation_record = (
            canonical_delegations.get(asserted_delegation_id)
            if asserted_delegation_id is not None
            and asserted_delegation_id == decision_delegation_id
            else None
        )
        delegation_evidence = self._ref_one(
            delegation_record,
            "delegations",
            ("delegation_id", "id"),
            ("starts_at",),
        )
        if asserted_delegation_id is None and decision_delegation_id is None:
            delegation_reference_state = "not_associated"
        elif (
            asserted_delegation_id is not None
            and decision_delegation_id is not None
            and asserted_delegation_id != decision_delegation_id
        ):
            delegation_reference_state = "conflicted"
        elif delegation_record is not None and delegation_evidence is not None:
            delegation_reference_state = "matched_canonical_record"
        else:
            delegation_reference_state = "unresolved"
        return {
            "executionId": execution_id,
            "decision": "allow" if decision["allowed"] else "deny",
            "assertedDelegationId": asserted_delegation_id,
            "recordedDecisionDelegationId": decision_delegation_id,
            "delegationId": (
                _first(delegation_record, "delegation_id", "id")
                if delegation_reference_state == "matched_canonical_record"
                else None
            ),
            "delegationReferenceState": delegation_reference_state,
            "delegationEvidenceRef": (
                delegation_evidence.model_dump(mode="json") if delegation_evidence else None
            ),
            "action": _first(snapshot, "action"),
            "resource": _first(snapshot, "resource"),
            "reason": _first(decision, "reason"),
            "decisionAt": _first(row, "started_at", "created_at"),
            "scope": "action_scoped_request_time_only",
            "evidenceRef": evidence.model_dump(mode="json"),
        }

    @classmethod
    def _execution_principals(cls, rows: list[dict[str, Any]], *, read: _Read) -> dict[str, Any]:
        candidates: dict[str, dict[str, Any]] = {}
        for row in rows:
            principal_id = _first(row, "initiating_principal_user_id")
            if principal_id is None:
                continue
            ref = cls._ref_one(
                row,
                "agent_executions",
                ("execution_id", "id"),
                ("started_at", "created_at"),
            )
            if ref is None:
                continue
            candidate = candidates.setdefault(
                principal_id,
                {
                    "principal": {"kind": "human", "id": principal_id},
                    "executionIds": [],
                    "evidenceRefs": [],
                },
            )
            execution_id = _first(row, "execution_id", "id")
            if execution_id is not None:
                candidate["executionIds"].append(execution_id)
            candidate["evidenceRefs"].append(ref.model_dump(mode="json"))

        complete = read.available and not read.truncated and not read.scope_mismatch
        state = (
            "unknown"
            if not read.available or not candidates
            else "partial"
            if not complete
            else "ambiguous"
            if len(candidates) > 1
            else "available"
        )
        principal = next(iter(candidates.values()))["principal"] if state == "available" else None
        evidence_refs = _dedupe_json_refs(
            [ref for candidate in candidates.values() for ref in candidate["evidenceRefs"]]
        )
        return {
            "state": state,
            "executionPrincipal": principal,
            "candidates": list(candidates.values()),
            "evidenceRefs": evidence_refs,
        }

    def _activity_view(self, row: dict[str, Any]) -> dict[str, Any]:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        ref = self._ref_one(
            row,
            "obs_agent_activities",
            ("observation_id", "activity_id", "id"),
            ("observed_at", "occurred_at"),
        )
        return {
            "observationId": _first(row, "observation_id", "activity_id", "id"),
            "eventName": _first(row, "event_name"),
            "actionName": _first(action, "name"),
            "actionStatus": _first(action, "status"),
            "observedAt": _first(row, "observed_at", "occurred_at"),
            "sourceProvider": _first(
                row.get("source", {}) if isinstance(row.get("source"), dict) else {}, "provider"
            ),
            "evidenceRef": ref.model_dump(mode="json") if ref else None,
        }

    def _tool_view(self, row: dict[str, Any]) -> dict[str, Any]:
        ref = self._ref_one(
            row,
            "obs_agent_tools",
            ("invocation_id", "tool_id", "id"),
            ("observed_at", "occurred_at"),
        )
        return {
            "invocationId": _first(row, "invocation_id", "tool_id", "id"),
            "toolName": _first(row, "tool_name"),
            "status": _first(row, "status"),
            "durationMs": row.get("duration_ms")
            if isinstance(row.get("duration_ms"), int)
            else None,
            "observedAt": _first(row, "observed_at", "occurred_at"),
            "evidenceRef": ref.model_dump(mode="json") if ref else None,
        }

    def _communication_view(self, row: dict[str, Any]) -> dict[str, Any]:
        ref = self._ref_one(
            row,
            "obs_agent_messages",
            ("message_obs_id", "id"),
            ("observed_at", "received_at"),
        )
        inbox_ref = EvidenceRef.model_validate(row["inbox_evidence_ref"])
        return {
            "messageObservationId": _first(row, "message_obs_id", "id"),
            "inboxObservationId": _first(row, "inbox_obs_id"),
            "threadObservationId": _first(row, "thread_obs_id"),
            "direction": _first(row, "direction"),
            "hasAttachments": (
                row.get("has_attachments") if isinstance(row.get("has_attachments"), bool) else None
            ),
            "observedAt": _first(row, "observed_at"),
            "receivedAt": _first(row, "received_at"),
            "subjectBindingBasis": _first(row, "subject_binding_basis"),
            "evidenceRef": ref.model_dump(mode="json") if ref else None,
            "bindingEvidenceRefs": [
                inbox_ref.model_dump(mode="json"),
                *([ref.model_dump(mode="json")] if ref else []),
            ],
            "contentBoundary": "observed_message_metadata_only",
        }

    def _execution_interactions(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        interactions: list[dict[str, Any]] = []
        for row in rows:
            ref = self._ref_one(
                row, "agent_executions", ("execution_id", "id"), ("started_at", "created_at")
            )
            if ref is None:
                continue
            policy_log = row.get("policy_log") if isinstance(row.get("policy_log"), dict) else {}
            for tool_name in _safe_strings(policy_log.get("tools_used")):
                interactions.append(
                    {
                        "kind": "execution_policy_log_tool_reference",
                        "toolName": tool_name,
                        "executionId": _first(row, "execution_id", "id"),
                        "evidenceRef": ref.model_dump(mode="json"),
                        "interpretation": "policy-log reference; not independently verified invocation",
                    }
                )
            for resource_name in _safe_strings(policy_log.get("resources")):
                interactions.append(
                    {
                        "kind": "execution_policy_log_resource_reference",
                        "resourceName": resource_name,
                        "executionId": _first(row, "execution_id", "id"),
                        "evidenceRef": ref.model_dump(mode="json"),
                        "interpretation": "policy-log reference; not independently verified resource use",
                    }
                )
        return interactions

    def _claims(
        self,
        *,
        request: ProjectionRequest,
        principal_identity_by_user_id: dict[str, dict[str, Any]],
        config: Optional[dict[str, Any]],
        config_ref: Optional[EvidenceRef],
        agent_identity_rows: list[dict[str, Any]],
        execution_rows: list[dict[str, Any]],
        delegation_records: list[tuple[dict[str, Any], str, bool]],
        delegation_party_identity_views: dict[tuple[str, str], dict[str, Any]],
        active_delegation_conflicts: list[dict[str, Any]],
        activity_rows: list[dict[str, Any]],
        tool_rows: list[dict[str, Any]],
        risk_rows: list[dict[str, Any]],
        communication_rows: list[dict[str, Any]],
    ) -> list[ClaimEnvelope]:
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)
        claims: list[ClaimEnvelope] = []
        for row in agent_identity_rows:
            source = _first(row, "identity_evidence_source")
            ref = (
                self._ref_one(
                    row,
                    source,
                    ("identity_evidence_id",),
                    ("identity_bound_at",),
                )
                if source
                else None
            )
            canonical_id = _first(row, "canonical_agent_entity_id")
            if ref is None or canonical_id is None:
                continue
            authority = _first(row, "identity_binding_authority")
            if authority == "canonical_agent_entity":
                claim_text = (
                    f"Subject {request.subject.id} is a tenant-scoped canonical Agent entity."
                )
            else:
                claim_text = f"A tenant-admin identity binding resolves the source agent reference to canonical Agent {canonical_id}."
            claims.append(
                ClaimEnvelope(
                    id=f"agent_identity_binding.{ref.id}",
                    kind="canonically_resolved_agent_identity",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[claim_text],
                    claimState=EpistemicStatus.RESOLVED,
                    domainSlotIds=["identity", "actor_attribution"],
                )
            )
        if config is not None and config_ref is not None:
            claims.append(
                ClaimEnvelope(
                    id=f"agent_config.{request.subject.id}",
                    kind="agent_configuration_observation",
                    subject=subject,
                    evidenceRefs=[config_ref],
                    claims=["A tenant-scoped agent configuration record is present."],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
        for row in execution_rows:
            ref = self._ref_one(
                row, "agent_executions", ("execution_id", "id"), ("started_at", "created_at")
            )
            if ref is None:
                continue
            execution_id = _first(row, "execution_id", "id")
            status = _first(row, "status")
            claims.append(
                ClaimEnvelope(
                    id=f"execution.{execution_id}",
                    kind="agent_execution_record",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[
                        f"Execution record {execution_id} is stored."
                        + (
                            f" Stored status: {status}."
                            if status
                            else " Stored status is unavailable."
                        )
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
            principal_user_id = _first(row, "initiating_principal_user_id")
            if principal_user_id is not None:
                claims.append(
                    ClaimEnvelope(
                        id=f"agent_execution_principal.{execution_id}",
                        kind="authenticated_execution_principal",
                        subject=subject,
                        evidenceRefs=[ref],
                        claims=[
                            f"AETHER recorded authenticated tenant user {principal_user_id} as the initiating principal for execution {execution_id}; this does not make that user the acting agent or establish a canonical human entity link."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["actor_attribution"],
                    )
                )
                principal_binding = principal_identity_by_user_id.get(principal_user_id)
                canonical_human_id = (
                    _first(principal_binding, "canonicalHumanEntityId")
                    if isinstance(principal_binding, dict)
                    else None
                )
                identity_refs = (
                    principal_binding.get("evidenceRefs", [])
                    if isinstance(principal_binding, dict)
                    else []
                )
                if canonical_human_id and isinstance(identity_refs, list):
                    claims.append(
                        ClaimEnvelope(
                            id=f"agent_execution_principal_identity.{execution_id}",
                            kind="canonically_resolved_execution_principal",
                            subject=subject,
                            evidenceRefs=[ref, *identity_refs],
                            claims=[
                                f"The authenticated principal for execution {execution_id} resolves through a tenant-scoped USER_ID alias to canonical Human entity {canonical_human_id}; this identity link does not establish action authorization."
                            ],
                            claimState=EpistemicStatus.RESOLVED,
                            domainSlotIds=["actor_attribution"],
                        )
                    )
            policy_log = row.get("policy_log") if isinstance(row.get("policy_log"), dict) else {}
            delegation_check = policy_log.get("delegation_check")
            if isinstance(delegation_check, dict) and isinstance(
                delegation_check.get("allowed"), bool
            ):
                decision = "allow" if delegation_check["allowed"] else "deny"
                snapshot = row.get("input_snapshot")
                snapshot = snapshot if isinstance(snapshot, dict) else {}
                action = _first(snapshot, "action") or "unknown action"
                resource = _first(snapshot, "resource") or "unknown resource"
                claims.append(
                    ClaimEnvelope(
                        id=f"agent_execution_delegation_decision.{execution_id}",
                        kind="server_recorded_delegation_decision",
                        subject=subject,
                        evidenceRefs=[ref],
                        claims=[
                            f"AETHER recorded a {decision} delegation-engine decision for {action} on {resource} in execution {execution_id}; this decision was action-scoped at request time and does not establish standing authority or prove external execution."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[
                            "authority_envelope",
                            "authority_check",
                            "policy_boundary",
                        ],
                    )
                )
        for row, _, active in delegation_records:
            ref = self._ref_one(row, "delegations", ("delegation_id", "id"), ("starts_at",))
            if ref is None:
                continue
            delegation_id = _first(row, "delegation_id", "id")
            claim_text = f"Delegation record {delegation_id} is stored."
            if active:
                claim_text += (
                    " The tenant-scoped delegation repository lists it in the active incoming set."
                )
            claim_text += " Effective action/resource authorization was not evaluated."
            claims.append(
                ClaimEnvelope(
                    id=f"delegation.{delegation_id}",
                    kind="agent_delegation_record",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[claim_text],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
            for side, field in (
                ("grantor", "grantor_entity_id"),
                ("grantee", "grantee_entity_id"),
            ):
                party_view = delegation_party_identity_views.get(
                    (delegation_id, side),
                    {
                        "state": "unknown",
                        "party": None,
                        "evidenceRefs": [ref.model_dump(mode="json")],
                        "reason": "tenant-scoped canonical party identity was not resolved",
                    },
                )
                party_id = _first(row, field)
                party_evidence: list[EvidenceRef] = []
                for raw_ref in party_view.get("evidenceRefs", []):
                    try:
                        party_evidence.append(EvidenceRef.model_validate(raw_ref))
                    except Exception:  # noqa: BLE001 - malformed identity evidence is omitted
                        continue
                party_state = party_view.get("state")
                resolved = party_state == "resolved" and isinstance(
                    party_view.get("party"), dict
                )
                claim_state = (
                    EpistemicStatus.RESOLVED
                    if resolved
                    else EpistemicStatus.DISPUTED
                    if party_state == "conflicted"
                    else EpistemicStatus.UNKNOWN
                )
                kind = (
                    "canonically_resolved_delegation_party"
                    if resolved
                    else "delegation_party_identity_resolution"
                )
                claims.append(
                    ClaimEnvelope(
                        id=f"delegation_party.{delegation_id}.{side}",
                        kind=kind,
                        subject=subject,
                        evidenceRefs=_dedupe_refs(party_evidence),
                        claims=[
                            (
                                f"The stored {side} party reference for delegation {delegation_id} resolves to a tenant-owned canonical {party_view['party']['kind']} entity; this identity link does not evaluate effective authorization."
                                if resolved
                                else f"The stored {side} party reference {party_id or 'missing'} for delegation {delegation_id} could not be uniquely resolved to a tenant-owned canonical entity: {party_view.get('reason') or 'identity is unknown'}."
                            )
                        ],
                        claimState=claim_state,
                        domainSlotIds=["owner_delegator", "delegation_chain", "actor_attribution"],
                    )
                )
        for conflict in active_delegation_conflicts:
            delegation_id = conflict.get("delegationId")
            raw_refs = conflict.get("evidenceRefs")
            if not isinstance(delegation_id, str) or not isinstance(raw_refs, list):
                continue
            refs: list[EvidenceRef] = []
            for raw_ref in raw_refs:
                try:
                    refs.append(EvidenceRef.model_validate(raw_ref))
                except Exception:  # noqa: BLE001 - malformed conflict evidence is omitted
                    continue
            refs = _dedupe_refs(refs)
            if not refs:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"delegation_active_state_conflict.{delegation_id}",
                    kind="agent_delegation_active_state_conflict",
                    subject=subject,
                    evidenceRefs=refs,
                    claims=[
                        f"Tenant-scoped delegation reads disagreed on fields for record {delegation_id}; its active state is unknown."
                    ],
                    claimState=EpistemicStatus.DISPUTED,
                    domainSlotIds=["delegation_chain", "authority_check"],
                )
            )
        for row in activity_rows:
            ref = self._ref_one(
                row,
                "obs_agent_activities",
                ("observation_id", "activity_id", "id"),
                ("observed_at", "occurred_at"),
            )
            if ref is None:
                continue
            event_name = _first(row, "event_name")
            claims.append(
                ClaimEnvelope(
                    id=f"observation.{ref.id}",
                    kind="agentic_observation_record",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[
                        f"An agentic observation record is stored{f' for event {event_name}' if event_name else ''}."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
        for row in tool_rows:
            ref = self._ref_one(
                row,
                "obs_agent_tools",
                ("invocation_id", "tool_id", "id"),
                ("observed_at", "occurred_at"),
            )
            if ref is None:
                continue
            tool_name = _first(row, "tool_name")
            claims.append(
                ClaimEnvelope(
                    id=f"tool.{ref.id}",
                    kind="agent_tool_invocation_record",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[
                        f"A tool invocation observation is stored{f' for {tool_name}' if tool_name else ''}."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
        for row in risk_rows:
            ref = self._ref_one(
                row, "obs_agent_risk_signals", ("signal_id", "id"), ("detected_at", "observed_at")
            )
            if ref is None:
                continue
            level = _first(row, "risk_level")
            claims.append(
                ClaimEnvelope(
                    id=f"risk_signal.{ref.id}",
                    kind="agent_risk_signal_record",
                    subject=subject,
                    evidenceRefs=[ref],
                    claims=[
                        f"An agent risk-signal record is stored{f' with level {level}' if level else ''}; it is not a composite risk assessment."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                )
            )
        for row in communication_rows:
            ref = self._ref_one(
                row,
                "obs_agent_messages",
                ("message_obs_id", "id"),
                ("observed_at", "received_at"),
            )
            if ref is None:
                continue
            inbox_ref = EvidenceRef.model_validate(row["inbox_evidence_ref"])
            direction = _first(row, "direction")
            claims.append(
                ClaimEnvelope(
                    id=f"agent_message.{ref.id}",
                    kind="agent_communication_observation",
                    subject=subject,
                    evidenceRefs=[inbox_ref, ref],
                    claims=[
                        "A tenant-scoped observed agent inbox is linked by exact inbox ID to an observed message record"
                        + (f" with direction {direction}." if direction else ".")
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["communications"],
                )
            )
        return claims

    @staticmethod
    def _unsupported_slots() -> list[dict[str, str]]:
        return [
            {
                "slot": "actor_attribution",
                "state": "partial",
                "reason": "authenticated initiating users resolve to canonical Humans only when an active tenant USER_ID alias exists; service principals and configured owner references remain unresolved",
            },
            {
                "slot": "authority_envelope",
                "state": "unknown",
                "reason": "stored grants and historical action-scoped decisions do not establish a current standing authority envelope",
            },
            {
                "slot": "policy_boundary",
                "state": "unknown",
                "reason": "the provider exposes no tenant policy snapshot or current effective authorization boundary",
            },
            {
                "slot": "communications",
                "state": "partial",
                "reason": "observed messages are joined through tenant agent inbox records; provider completeness and message bodies are unavailable",
            },
            {
                "slot": "business_outcomes",
                "state": "unknown",
                "reason": "execution status is not a measured business outcome; outcome360 owns that binding",
            },
            {
                "slot": "economic_cost_and_settlement",
                "state": "unknown",
                "reason": "economic360 owns payment and settlement facts; no canonical economic fact is joined here",
            },
            {
                "slot": "risk_summary",
                "state": "partial",
                "reason": "risk, social, and relationship assessments are composed by their canonical projections; this provider's stored signals are observations, not a composite score",
            },
            {
                "slot": "spawned_agents",
                "state": "unknown",
                "reason": "spawned-agent graph relationships are delegated to Relationship360 and may remain incomplete without a ledger coverage watermark",
            },
        ]

    @staticmethod
    def _dependency_state(context: ProjectionContext, projection_id: str) -> str:
        for dependency in context.dependencyState:
            if dependency.projectionId == projection_id:
                return dependency.state
        return "unknown"

    def _unsupported_subject(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        *,
        reason: Optional[str] = None,
        degraded_reason: Optional[str] = None,
    ) -> ProjectionResult:
        reason = reason or "Agent360 accepts agent or verified canonical Agent entity subjects only"
        sections = [
            ProjectionSection(
                id=section_id,
                state="unknown",
                title=section_id,
                content={"state": "unknown", "reason": reason},
            )
            for section_id in OUTPUT_SECTIONS
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=_utc_now_iso(),
            degradedReasons=[degraded_reason] if degraded_reason else [],
            temporalMode=request.temporalMode,
            lensIds=request.lensIds,
        )

    def _unsupported_temporal_mode(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        reason = "Agent 360 repositories do not expose bitemporal replay; current rows are not served as an as-of or compare answer"
        sections = [
            ProjectionSection(
                id=section_id,
                state="unknown" if section_id != "timeline" else "degraded",  # type: ignore[arg-type]
                title=section_id,
                content={
                    "state": "unknown",
                    "requestedTemporalMode": request.temporalMode,
                    "reason": reason,
                },
                warnings=["historical_agent_state_unavailable"],
            )
            for section_id in OUTPUT_SECTIONS
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=_utc_now_iso(),
            degradedReasons=[REASON_TEMPORAL_REPLAY_UNAVAILABLE],
            temporalMode=request.temporalMode,
            lensIds=request.lensIds,
        )


def _merge_reads(*reads: _Read) -> _Read:
    if any(not read.available for read in reads):
        return _Read(
            rows=None,
            available=False,
            truncated=any(read.truncated for read in reads),
            scope_mismatch=any(read.scope_mismatch for read in reads),
            scope_known=all(read.scope_known for read in reads),
        )
    rows = [row for read in reads for row in (read.rows or [])]
    return _Read(
        rows=rows,
        available=True,
        truncated=any(read.truncated for read in reads),
        scope_mismatch=any(read.scope_mismatch for read in reads),
        scope_known=all(read.scope_known for read in reads),
    )


def register_provider(registry: ProviderRegistry) -> None:
    """Register explicitly from central projection wiring; never at import time."""
    registry.register(Agent360Provider(), source="services/api/actions/agent")


__all__ = [
    "Agent360Provider",
    "Agent360Source",
    "OUTPUT_SECTIONS",
    "RepositoryAgent360Source",
    "register_provider",
]
