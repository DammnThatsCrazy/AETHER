"""Tenant-scoped Social360 projection over canonical Social Silver facts.

This projection reports persisted social observations. It does not derive a
universal influence score, promote observations into graph relationships, or
turn unavailable coverage into zero. Relationship subjects use the canonical
``source_entity::target_entity`` pair form shared with Relationship360 and only
surface Social Silver facts that are bound to those exact endpoints.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.composition import PRODUCT_360_SURFACE_DEFINITIONS
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
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
from governance.consent.authority import evaluate_consent
from identity.population360.scope import (
    PopulationScopeRead,
    PopulationScopeReader,
    RepositoryPopulationScopeReader,
)
from identity.identity.source_subject_scope import (
    RepositorySourceSubjectScopeReader,
    SourceSubjectScopeRead,
    SourceSubjectScopeReader,
)


PROJECTION_ID = "social360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "findings",
    "interactions",
    "paths",
    "propagation",
    "state",
    "summary",
    "timeline",
)
_MAX_READ_ROWS = 500
_SOCIAL_PATH_DEPTH = 3
_SOCIAL_PATH_NODE_LIMIT = 100
_SOCIAL_PATH_EDGE_LIMIT = 500
_SOCIAL_PATH_RESULT_LIMIT = 50
_SOCIAL_PATH_AUTHORITIES = ["graph", "relationship_facts"]
_SOCIAL_PROPAGATION_AUTHORITIES = [
    "graph",
    "relationship_facts",
    "relationship_predicate_registry",
    "influence_propagation",
]
_FACT_TABLES = (
    "identity",
    "connection",
    "interaction",
    "content",
    "community",
    "metric",
)


@dataclass(frozen=True)
class AgentSubjectScopeRead:
    """Verified tenant Agent reference to a canonical Agent entity."""

    tenant_id: str
    agent_id: str
    state: Literal["available", "unknown", "degraded", "conflicted"]
    canonical_agent_entity_id: Optional[str] = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None


class AgentSubjectScopeReader(Protocol):
    """Resolve an Agent subject through canonical Agent identity authority."""

    async def resolve(self, tenant_id: str, agent_id: str) -> AgentSubjectScopeRead: ...


class RepositoryAgentSubjectScopeReader:
    """Adapter over the source-to-canonical Agent identity resolver."""

    def __init__(
        self, *, deployments: Any = None, identity_bindings: Any = None, entities: Any = None
    ):
        self._deployments = deployments
        self._identity_bindings = identity_bindings
        self._entities = entities

    async def resolve(self, tenant_id: str, agent_id: str) -> AgentSubjectScopeRead:
        if self._deployments is None:
            from actions.agent.deployments import get_deployment_repository

            self._deployments = get_deployment_repository()
        if self._identity_bindings is None:
            from actions.agent_marketplace.identity_binding import (
                AgentDeploymentIdentityBindingRepository,
            )

            self._identity_bindings = AgentDeploymentIdentityBindingRepository()
        if self._entities is None:
            from repositories.repos import EntityRepository

            self._entities = EntityRepository()
        from actions.agent.identity_resolution import resolve_agent_identities

        try:
            result = await resolve_agent_identities(
                tenant_id,
                {agent_id},
                deployments=self._deployments,
                identity_bindings=self._identity_bindings,
                entities=self._entities,
                limit=_MAX_READ_ROWS,
            )
        except Exception:  # noqa: BLE001 - canonical identity authority is fail-closed
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "degraded", reason="agent_identity_authority_unavailable"
            )
        if result.truncated:
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "degraded", reason="agent_identity_scan_truncated"
            )
        if result.scope_mismatch:
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "conflicted", reason="agent_identity_scope_conflict"
            )

        rows = [row for row in result.rows if isinstance(row, dict)]
        if not rows:
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "unknown", reason="agent_canonical_identity_unresolved"
            )
        canonical_ids = {
            row.get("canonical_agent_entity_id")
            for row in rows
            if row.get("tenant_id") == tenant_id and row.get("agent_id") == agent_id
        }
        if len(canonical_ids) != 1 or not all(
            isinstance(value, str) and value for value in canonical_ids
        ):
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "conflicted", reason="agent_identity_binding_conflicted"
            )
        canonical_id = next(iter(canonical_ids))
        if len(rows) != len(canonical_ids) and any(
            row.get("tenant_id") != tenant_id
            or row.get("agent_id") != agent_id
            or row.get("canonical_agent_entity_id") != canonical_id
            for row in rows
        ):
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "conflicted", reason="agent_identity_scope_conflict"
            )
        refs = tuple(
            EvidenceRef(
                id=str(row.get("identity_evidence_id")),
                type="entity",
                source=str(row.get("identity_evidence_source")),
                observedAt=row.get("identity_bound_at"),
            )
            for row in rows
            if row.get("identity_evidence_id")
            and row.get("identity_evidence_source")
            and row.get("tenant_id") == tenant_id
            and row.get("agent_id") == agent_id
            and row.get("canonical_agent_entity_id") == canonical_id
        )
        if not refs:
            return AgentSubjectScopeRead(
                tenant_id, agent_id, "degraded", reason="agent_identity_evidence_unavailable"
            )
        return AgentSubjectScopeRead(
            tenant_id,
            agent_id,
            "available",
            canonical_agent_entity_id=canonical_id,
            evidence_refs=tuple(_dedupe_refs(list(refs))),
        )


@dataclass(frozen=True)
class Social360FactRead:
    """One bounded source read with explicit availability and truncation."""

    rows: list[dict[str, Any]]
    available: bool = True
    truncated: bool = False
    reason: Optional[str] = None


class Social360Source(Protocol):
    """Narrow testable read seam over the six Social Silver fact authorities."""

    async def read(self, fact_family: str, tenant_id: str, *, limit: int) -> Social360FactRead: ...


@dataclass(frozen=True)
class SocialObservedPath:
    """One directed path made only from observed canonical FOLLOWS edges."""

    entity_ids: tuple[str, ...]
    edge_evidence_refs: tuple[tuple[EvidenceRef, ...], ...]
    graph_edges: tuple[Any, ...] = ()
    edge_observed_at: tuple[Optional[str], ...] = ()


@dataclass(frozen=True)
class SocialGraphPathRead:
    """Bounded tenant-scoped read from the canonical relationship graph."""

    tenant_id: str
    start_entity_id: str
    paths: tuple[SocialObservedPath, ...] = ()
    available: bool = True
    truncated: bool = False
    reason_codes: tuple[str, ...] = ()


class SocialGraphPathReader(Protocol):
    """Read observed canonical graph paths without deriving trust or influence."""

    async def read_paths(self, tenant_id: str, start_entity_id: str) -> SocialGraphPathRead: ...


class RepositorySocialGraphPathReader:
    """Resolve bounded paths over registered tenant-scoped FOLLOWS graph edges."""

    def __init__(self, *, graph_client: Any = None) -> None:
        self._graph_client = graph_client

    async def read_paths(self, tenant_id: str, start_entity_id: str) -> SocialGraphPathRead:
        from shared.graph.graph import get_graph_client, tenant_of
        from shared.relationship_spine.relationship_registry import (
            live_graph_edge_type,
            predicate_entry,
        )

        entry = predicate_entry("FOLLOWS")
        edge_type = live_graph_edge_type("FOLLOWS")
        if (
            not entry
            or entry.get("family") != "SOCIAL"
            or entry.get("graphRegistrationState") != "REGISTERED"
            or "NON_TRANSITIVE" not in entry.get("transitivityClasses", [])
            or edge_type is None
        ):
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("registered_social_follows_authority_unavailable",),
            )

        client = self._graph_client or get_graph_client()
        try:
            anchor = await client.get_vertex_for_tenant(tenant_id, start_entity_id)
            if anchor is None or tenant_of(anchor.properties) != tenant_id:
                # Do not distinguish a missing vertex from a foreign-tenant id.
                return SocialGraphPathRead(
                    tenant_id,
                    start_entity_id,
                    reason_codes=("canonical_graph_subject_unresolved",),
                )
            edge_page = await client.get_edges_for_tenant(
                tenant_id,
                limit=_SOCIAL_PATH_EDGE_LIMIT,
                edge_types=[edge_type],
                include_revoked=False,
            )
        except Exception:  # noqa: BLE001 - graph authority failures fail closed
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("canonical_social_graph_authority_unavailable",),
            )

        if (
            not isinstance(edge_page, tuple)
            or len(edge_page) != 2
            or not isinstance(edge_page[0], list)
            or not isinstance(edge_page[1], bool)
        ):
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("invalid_canonical_social_graph_read_contract",),
            )
        tenant_edges, edges_truncated = edge_page

        now = datetime.now(timezone.utc)
        candidate_edges: dict[
            str, list[tuple[str, tuple[EvidenceRef, ...], str, Any, Optional[str]]]
        ] = {}
        reasons: set[str] = set()
        if edges_truncated:
            reasons.add("canonical_social_path_edge_scan_capped")

        for edge_index, edge in enumerate(tenant_edges):
            if edge_index >= _SOCIAL_PATH_EDGE_LIMIT:
                edges_truncated = True
                reasons.add("canonical_social_path_edge_scan_capped")
                break
            props = edge.properties or {}
            if (
                edge.edge_type != edge_type
                or tenant_of(props) != tenant_id
                or props.get("relationship_predicate") != "FOLLOWS"
                or _truthy_marker(props.get("revoked"))
                or bool(props.get("revoked_at"))
            ):
                if tenant_of(props) != tenant_id:
                    reasons.add("canonical_social_path_scope_mismatch")
                continue

            valid_from = _parse_graph_time(props.get("valid_from"))
            valid_to_value = props.get("valid_to")
            valid_to = _parse_graph_time(valid_to_value) if valid_to_value else None
            valid_from_value = props.get("valid_from")
            if (valid_to_value and valid_to is None) or (valid_from_value and valid_from is None):
                reasons.add("canonical_social_path_validity_unknown")
                continue
            if valid_from is not None and valid_from > now:
                continue
            if valid_to is not None and valid_to <= now:
                continue

            idempotency_key = _text(props.get("idempotency_key"))
            evidence_ids = _graph_evidence_ids(props.get("evidence_refs"))
            if idempotency_key is None or not evidence_ids:
                reasons.add("canonical_social_path_edge_evidence_unavailable")
                continue

            # valid_from is relationship validity time. Preserve an explicit
            # source observation time separately; validity time cannot prove
            # chronological order between social observations.
            observed_at_value = _text(props.get("observed_at"))
            observed_at = _parse_graph_time(observed_at_value)
            refs = [
                EvidenceRef(
                    id=idempotency_key,
                    type="relationship",
                    source="entity_graph",
                    observedAt=valid_from.isoformat() if valid_from is not None else None,
                ),
                *[
                    EvidenceRef(
                        id=evidence_id,
                        type="event",
                        source="relationship_facts",
                    )
                    for evidence_id in evidence_ids
                ],
            ]
            candidate_edges.setdefault(edge.from_vertex_id, []).append(
                (
                    edge.to_vertex_id,
                    tuple(refs),
                    idempotency_key,
                    edge,
                    observed_at.isoformat() if observed_at is not None else None,
                )
            )

        for outgoing in candidate_edges.values():
            outgoing.sort(key=lambda item: (item[0], item[2]))

        nodes = {start_entity_id: anchor}
        node_depths = {start_entity_id: 0}
        queue = [start_entity_id]
        adjacency: dict[
            str, list[tuple[str, tuple[EvidenceRef, ...], str, Any, Optional[str]]]
        ] = {}
        node_scan_truncated = False
        while queue:
            current_id = queue.pop(0)
            depth = node_depths[current_id]
            if depth >= _SOCIAL_PATH_DEPTH:
                continue
            for target_id, refs, edge_key, graph_edge, observed_at in candidate_edges.get(
                current_id, []
            ):
                if target_id not in nodes:
                    if len(nodes) >= _SOCIAL_PATH_NODE_LIMIT:
                        node_scan_truncated = True
                        reasons.add("canonical_social_path_node_scan_capped")
                        continue
                    try:
                        target = await client.get_vertex_for_tenant(tenant_id, target_id)
                    except Exception:  # noqa: BLE001 - tenant-scoped vertex read is fail-closed
                        return SocialGraphPathRead(
                            tenant_id,
                            start_entity_id,
                            available=False,
                            reason_codes=("canonical_social_graph_authority_unavailable",),
                        )
                    if target is None or tenant_of(target.properties) != tenant_id:
                        reasons.add("canonical_social_path_endpoint_unresolved")
                        continue
                    nodes[target_id] = target
                    node_depths[target_id] = depth + 1
                    queue.append(target_id)
                adjacency.setdefault(current_id, []).append(
                    (target_id, refs, edge_key, graph_edge, observed_at)
                )

        for outgoing in adjacency.values():
            outgoing.sort(key=lambda item: (item[0], item[2]))

        paths: list[SocialObservedPath] = []
        path_scan_truncated = False

        def visit(
            current_id: str,
            entity_ids: tuple[str, ...],
            edge_refs: tuple[tuple[EvidenceRef, ...], ...],
            graph_edges: tuple[Any, ...],
            edge_observed_at: tuple[Optional[str], ...],
        ) -> None:
            nonlocal path_scan_truncated
            hops = len(edge_refs)
            if hops >= 2:
                if len(paths) >= _SOCIAL_PATH_RESULT_LIMIT:
                    path_scan_truncated = True
                    return
                paths.append(
                    SocialObservedPath(entity_ids, edge_refs, graph_edges, edge_observed_at)
                )
            if hops >= _SOCIAL_PATH_DEPTH or path_scan_truncated:
                return
            for next_id, refs, _edge_key, graph_edge, observed_at in adjacency.get(
                current_id, []
            ):
                if next_id in entity_ids:
                    continue
                visit(
                    next_id,
                    (*entity_ids, next_id),
                    (*edge_refs, refs),
                    (*graph_edges, graph_edge),
                    (*edge_observed_at, observed_at),
                )
                if path_scan_truncated:
                    return

        visit(start_entity_id, (start_entity_id,), (), (), ())
        truncated = edges_truncated or node_scan_truncated or path_scan_truncated
        if truncated:
            reasons.add("canonical_social_path_read_bounded")
        if not paths and not reasons and not truncated:
            reasons.add("no_bounded_observed_follows_paths")
        return SocialGraphPathRead(
            tenant_id,
            start_entity_id,
            paths=tuple(paths),
            available=True,
            truncated=truncated,
            reason_codes=tuple(sorted(reasons)),
        )


class RepositorySocial360Source:
    """Read tenant-scoped rows from the durable Social Silver repositories."""

    def __init__(self) -> None:
        from ingestion.silver.repositories.social_facts import (
            SocialCommunityFactsRepository,
            SocialConnectionFactsRepository,
            SocialContentFactsRepository,
            SocialIdentityFactsRepository,
            SocialInteractionFactsRepository,
            SocialMetricFactsRepository,
        )

        self._repositories = {
            "identity": SocialIdentityFactsRepository(),
            "connection": SocialConnectionFactsRepository(),
            "interaction": SocialInteractionFactsRepository(),
            "content": SocialContentFactsRepository(),
            "community": SocialCommunityFactsRepository(),
            "metric": SocialMetricFactsRepository(),
        }

    async def read(self, fact_family: str, tenant_id: str, *, limit: int) -> Social360FactRead:
        repository = self._repositories.get(fact_family)
        if repository is None:
            return Social360FactRead(
                rows=[], available=False, reason="social_fact_family_unavailable"
            )
        try:
            # The repository caps at 500. A full page therefore means the read
            # may be truncated; it is never described as complete coverage.
            rows = await repository.list_for_tenant(
                tenant_id, limit=min(max(limit, 1), _MAX_READ_ROWS)
            )
        except Exception:  # noqa: BLE001 - source failures become typed degradation
            return Social360FactRead(
                rows=[], available=False, reason=f"{fact_family}_source_unavailable"
            )
        return Social360FactRead(
            rows=rows if isinstance(rows, list) else [],
            available=isinstance(rows, list),
            truncated=isinstance(rows, list) and len(rows) >= _MAX_READ_ROWS,
            reason=None if isinstance(rows, list) else "invalid_source_contract",
        )


class Social360Provider(IntelligenceProjectionProvider):
    """Read authorized social observations without fabricating missing state."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        *,
        source: Optional[Social360Source] = None,
        consent_reader: Any = None,
        population_scope_reader: Optional[PopulationScopeReader] = None,
        source_subject_scope_reader: Optional[SourceSubjectScopeReader] = None,
        agent_subject_scope_reader: Optional[AgentSubjectScopeReader] = None,
        social_graph_path_reader: Optional[SocialGraphPathReader] = None,
    ) -> None:
        self._source = source if source is not None else RepositorySocial360Source()
        self._consent_reader = consent_reader or evaluate_consent
        self._population_scope = (
            population_scope_reader
            if population_scope_reader is not None
            else RepositoryPopulationScopeReader()
        )
        self._source_subject_scope = (
            source_subject_scope_reader
            if source_subject_scope_reader is not None
            else RepositorySourceSubjectScopeReader()
        )
        self._agent_subject_scope = (
            agent_subject_scope_reader
            if agent_subject_scope_reader is not None
            else RepositoryAgentSubjectScopeReader()
        )
        self._social_graph_paths = (
            social_graph_path_reader
            if social_graph_path_reader is not None
            else RepositorySocialGraphPathReader()
        )

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        now = datetime.now(timezone.utc).isoformat()
        if not request.tenantId or not request.subject.id:
            raise ValueError("tenant and subject are required")

        # Runtime context is the authenticated tenant boundary. Reject a direct
        # caller with a mismatched tenant before invoking either authority.
        if context.tenantId != request.tenantId:
            return self._unknown_result(
                request,
                context,
                now,
                "tenant_scope_mismatch",
                subject=request.subject,
            )

        population_scope: Optional[PopulationScopeRead] = None
        source_scope: Optional[SourceSubjectScopeRead] = None
        agent_scope: Optional[AgentSubjectScopeRead] = None
        if request.subject.kind == "population":
            has_temporal_filter = (
                request.asOf is not None
                or context.asOf is not None
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
                or (request.temporalMode or "window") != "window"
            )
            if has_temporal_filter:
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "population_membership_temporal_scope_unknown",
                    subject=request.subject,
                )
            try:
                population_scope = await self._population_scope.resolve(
                    request.tenantId, request.subject.id, limit=_MAX_READ_ROWS
                )
            except Exception:  # noqa: BLE001 - population authority is fail-closed
                population_scope = PopulationScopeRead(
                    request.tenantId,
                    request.subject.id,
                    "degraded",
                    reason="population_membership_authority_unavailable",
                )
            if (
                population_scope.tenant_id != request.tenantId
                or population_scope.population_id != request.subject.id
            ):
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "population_membership_scope_mismatch",
                    subject=request.subject,
                )
            if population_scope.state == "empty":
                return self._empty_population_result(request, context, now, population_scope)
            if population_scope.state != "available":
                return self._unknown_result(
                    request,
                    context,
                    now,
                    population_scope.reason or "population_membership_scope_unavailable",
                    subject=request.subject,
                )
            endpoints = population_scope.entity_ids
        elif request.subject.kind == "source":
            has_temporal_filter = (
                request.asOf is not None
                or context.asOf is not None
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
                or (request.temporalMode or "window") != "window"
            )
            if has_temporal_filter:
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "source_identity_temporal_scope_unknown",
                    subject=request.subject,
                )
            try:
                source_scope = await self._source_subject_scope.resolve(
                    request.tenantId, request.subject.id
                )
            except Exception:  # noqa: BLE001 - canonical source identity is fail-closed
                source_scope = SourceSubjectScopeRead(
                    request.tenantId,
                    request.subject.id,
                    "degraded",
                    reason="source_identity_authority_unavailable",
                )
            if (
                source_scope.tenant_id != request.tenantId
                or source_scope.source_identity_id != request.subject.id
            ):
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "source_identity_scope_mismatch",
                    subject=request.subject,
                )
            if source_scope.state != "available" or not source_scope.canonical_entity_id:
                return self._unknown_result(
                    request,
                    context,
                    now,
                    source_scope.reason or "source_identity_binding_unresolved",
                    subject=request.subject,
                )
            endpoints = (source_scope.canonical_entity_id,)
        elif request.subject.kind == "agent":
            has_temporal_filter = (
                request.asOf is not None
                or context.asOf is not None
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
                or (request.temporalMode or "window") != "window"
            )
            if has_temporal_filter:
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "agent_identity_temporal_scope_unknown",
                    subject=request.subject,
                )
            try:
                agent_scope = await self._agent_subject_scope.resolve(
                    request.tenantId, request.subject.id
                )
            except Exception:  # noqa: BLE001 - canonical identity is fail-closed
                agent_scope = AgentSubjectScopeRead(
                    request.tenantId,
                    request.subject.id,
                    "degraded",
                    reason="agent_identity_authority_unavailable",
                )
            if (
                agent_scope.tenant_id != request.tenantId
                or agent_scope.agent_id != request.subject.id
            ):
                return self._unknown_result(
                    request,
                    context,
                    now,
                    "agent_identity_scope_mismatch",
                    subject=request.subject,
                )
            if agent_scope.state != "available" or not agent_scope.canonical_agent_entity_id:
                return self._unknown_result(
                    request,
                    context,
                    now,
                    agent_scope.reason or "agent_canonical_identity_unresolved",
                    subject=request.subject,
                )
            endpoints = (agent_scope.canonical_agent_entity_id,)
        else:
            endpoints = _subject_endpoints(request.subject)
        if endpoints is None:
            return self._unknown_result(
                request,
                context,
                now,
                "social_subject_binding_unsupported",
                subject=request.subject,
            )

        consent_results = []
        for endpoint in endpoints:
            try:
                consent_results.append(
                    await self._consent_reader(request.tenantId, endpoint, None, "analytics")
                )
            except Exception:  # noqa: BLE001 - consent is a fail-closed read gate
                consent_results.append((False, "consent_authority_unavailable"))
        denied = [result for result in consent_results if not _consent_allowed(result)]
        if denied:
            return self._suppressed_result(
                request,
                context,
                now,
                "consent_required",
                subject=request.subject,
            )

        include = set(request.includeSections or OUTPUT_SECTIONS)
        path_read = SocialGraphPathRead(
            request.tenantId,
            request.subject.id,
            available=False,
            reason_codes=("multi_hop_paths_entity_subject_required",),
        )
        propagation_read = SocialGraphPathRead(
            request.tenantId,
            request.subject.id,
            available=False,
            reason_codes=("social_propagation_subject_scope_unavailable",),
        )
        temporal_filter_requested = (
            request.asOf is not None
            or context.asOf is not None
            or (
                request.timeRange is not None
                and (request.timeRange.from_ is not None or request.timeRange.to is not None)
            )
            or (request.temporalMode or "window") in {"as_of", "relative"}
        )
        consent_by_endpoint = {
            endpoint: _consent_allowed(consent)
            for endpoint, consent in zip(endpoints, consent_results)
        }
        if "paths" in include:
            if request.subject.kind == "entity" and temporal_filter_requested:
                path_read = SocialGraphPathRead(
                    request.tenantId,
                    request.subject.id,
                    available=False,
                    reason_codes=("social_graph_path_temporal_scope_unsupported",),
                )
            elif request.subject.kind == "entity":
                path_read = await self._read_social_paths(request.tenantId, request.subject.id)
                path_read = await self._authorize_social_paths(
                    path_read,
                    request.tenantId,
                    request.subject.id,
                    already_checked=consent_by_endpoint,
                )

        if "propagation" in include:
            if temporal_filter_requested:
                propagation_read = SocialGraphPathRead(
                    request.tenantId,
                    endpoints[0] if request.subject.kind == "relationship" else request.subject.id,
                    available=False,
                    reason_codes=("social_propagation_temporal_scope_unsupported",),
                )
            elif request.subject.kind == "entity" and "paths" in include:
                # The entity path section and propagation section share the
                # same authorized canonical graph read.
                propagation_read = path_read
            elif request.subject.kind in {"entity", "relationship"}:
                propagation_start = endpoints[0]
                propagation_read = await self._read_social_paths(
                    request.tenantId, propagation_start
                )
                propagation_read = await self._authorize_social_paths(
                    propagation_read,
                    request.tenantId,
                    propagation_start,
                    already_checked=consent_by_endpoint,
                )
                if request.subject.kind == "relationship":
                    target_entity_id = endpoints[1]
                    pair_paths = tuple(
                        path
                        for path in propagation_read.paths
                        if path.entity_ids[-1] == target_entity_id
                    )
                    if not pair_paths and not propagation_read.reason_codes:
                        pair_reasons = ("no_bounded_observed_propagation_paths_for_pair",)
                    else:
                        pair_reasons = propagation_read.reason_codes
                    propagation_read = SocialGraphPathRead(
                        request.tenantId,
                        propagation_start,
                        paths=pair_paths,
                        available=propagation_read.available,
                        truncated=propagation_read.truncated,
                        reason_codes=pair_reasons,
                    )
            else:
                propagation_read = SocialGraphPathRead(
                    request.tenantId,
                    request.subject.id,
                    available=False,
                    reason_codes=("social_propagation_entity_or_relationship_subject_required",),
                )

        reads: dict[str, Social360FactRead] = {}
        reads["identity"] = await self._read("identity", request.tenantId)
        tenant_identity_rows, bad_identity_scope = _tenant_rows(reads["identity"], request.tenantId)
        if not reads["identity"].available:
            # A reader may return a partial page alongside an unavailable
            # status. Those rows cannot establish an identity join.
            tenant_identity_rows = []
            bad_identity_scope = False
        entity_ids = set(endpoints)
        identity_rows = [
            row
            for row in tenant_identity_rows
            if _text(row.get("canonical_entity_ref")) in entity_ids
        ]

        # Social identity references can be bound to more than one entity in
        # dirty or conflicting data. Remove those references before joining
        # any other social fact family.
        identity_ids, ambiguous_identity_ids = _unique_identity_ids(
            tenant_identity_rows, entity_ids
        )
        subject_identity_rows = [
            row for row in identity_rows if _text(row.get("social_identity_id")) in identity_ids
        ]

        scoped: dict[str, list[dict[str, Any]]] = {"identity": subject_identity_rows}
        scope_mismatch = bad_identity_scope or bool(ambiguous_identity_ids)
        queried_families = {"identity"}
        if identity_ids:
            for family in _FACT_TABLES[1:]:
                reads[family] = await self._read(family, request.tenantId)
                queried_families.add(family)
                rows, bad_scope = _tenant_rows(reads[family], request.tenantId)
                if not reads[family].available:
                    # Do not turn a partial failed read into evidence-backed
                    # claims; its coverage remains explicit below.
                    rows = []
                    bad_scope = False
                scope_mismatch = scope_mismatch or bad_scope
                scoped[family] = _subject_rows(
                    family,
                    rows,
                    request.subject,
                    identity_ids,
                    _identity_ids_by_entity(subject_identity_rows),
                    population_entity_ids=entity_ids
                    if request.subject.kind == "population"
                    else None,
                )
        else:
            for family in _FACT_TABLES[1:]:
                reads[family] = Social360FactRead(rows=[], available=True)
                scoped[family] = []

        # Time filters operate on the source event/observation time. For an
        # as-of read, received_at is the knowledge-time anchor. Rows without a
        # usable timestamp are omitted from bounded temporal results.
        temporal_unknown = False
        for family, rows in list(scoped.items()):
            filtered, unknown = _filter_temporal(rows, request, context.asOf)
            scoped[family] = filtered
            temporal_unknown = temporal_unknown or unknown

        identities = scoped["identity"]
        connections = scoped["connection"]
        interactions = scoped["interaction"]
        content = scoped["content"]
        communities = scoped["community"]
        metrics = scoped["metric"]

        identity_items = _visible_items(
            identities,
            "silver_social_identity_facts",
            (
                "social_identity_id",
                "provider_identity",
                "account_type",
                "verification_state",
                "resolution_state",
                "resolution_confidence",
                "identity_evidence_refs",
            ),
        )
        connection_items = _visible_items(
            connections,
            "silver_social_connection_facts",
            (
                "source_social_identity_ref",
                "target_social_identity_ref",
                "connection_type",
                "directionality",
                "proof_level",
                "claim_type",
                "evidence_refs",
                "contradictory_evidence_refs",
            ),
        )
        interaction_items = _visible_items(
            interactions,
            "silver_social_interaction_facts",
            (
                "interaction_id",
                "actor_social_identity_ref",
                "target_social_identity_ref",
                "interaction_type",
                "observed_at",
                "machine_classification",
                "human_qualification",
                "evidence_refs",
            ),
        )
        content_items = _visible_items(
            content,
            "silver_social_content_facts",
            (
                "content_id",
                "author_social_identity_ref",
                "content_type",
                "provider_content_subtype",
                "parent_content_ref",
                "root_content_ref",
                "published_at",
                "edited_at",
                "deleted_at",
                "content_hash",
                "semantic_ref",
                "narrative_refs",
                "campaign_ref",
                "incentive_context_ref",
                "evidence_refs",
            ),
        )
        community_items = _visible_items(
            communities,
            "silver_social_community_facts",
            (
                "membership_id",
                "social_identity_ref",
                "community_ref",
                "membership_role",
                "provider_membership_role",
                "valid_from",
                "valid_to",
                "observed_at",
                "evidence_refs",
            ),
        )
        metric_items = _visible_items(
            metrics,
            "silver_social_metric_facts",
            (
                "metric_observation_id",
                "social_identity_ref",
                "metric_name",
                "value",
                "unit",
                "status",
                "metric_window",
                "population",
                "observed_at",
                "computation_ref",
                "quality",
                "evidence_refs",
            ),
        )

        rows_by_family = {
            "identity": identities,
            "connection": connections,
            "interaction": interactions,
            "content": content,
            "community": communities,
            "metric": metrics,
        }
        identity_binding_state = _identity_binding_state(
            reads["identity"],
            identity_ids,
            ambiguous_identity_ids,
            bad_identity_scope,
        )
        identity_scope_incomplete = identity_binding_state in {
            "unavailable",
            "truncated",
            "degraded",
        }
        refs_by_family = {
            family: [
                ref
                for row in rows
                if (ref := _row_evidence(row, f"silver_social_{family}_facts")) is not None
            ]
            for family, rows in rows_by_family.items()
        }
        all_refs = _dedupe_refs(
            [
                *(population_scope.evidence_refs if population_scope is not None else ()),
                *(source_scope.evidence_refs if source_scope is not None else ()),
                *(agent_scope.evidence_refs if agent_scope is not None else ()),
                *(ref for refs in refs_by_family.values() for ref in refs),
            ]
        )

        source_status = _source_status(reads, families=_FACT_TABLES)
        if not identity_ids and source_status == "available":
            source_status = "unresolved"
        if scope_mismatch or temporal_unknown:
            source_status = (
                "degraded"
                if source_status in {"available", "empty", "unresolved"}
                else source_status
            )

        identity_count_known = (
            bool(identity_ids)
            and not reads["identity"].truncated
            and not scope_mismatch
            and not temporal_unknown
        )
        source_coverage = _source_coverage(
            reads,
            rows_by_family,
            queried_families=queried_families,
            overall_state=source_status,
            identity_binding_state=identity_binding_state,
            scope_mismatch=scope_mismatch,
            temporal_unknown=temporal_unknown,
            temporal_bounded=(
                (request.temporalMode or "window") in {"as_of", "relative"}
                or (
                    request.timeRange is not None
                    and (request.timeRange.from_ is not None or request.timeRange.to is not None)
                )
            ),
        )
        section_data = {
            "evidence": (
                "Evidence",
                all_refs,
                {
                    "evidenceRefs": all_refs,
                    "populationMembershipEvidenceRefs": (
                        list(population_scope.evidence_refs) if population_scope is not None else []
                    ),
                    "sourceIdentityEvidenceRefs": (
                        list(source_scope.evidence_refs) if source_scope is not None else []
                    ),
                    "agentIdentityEvidenceRefs": (
                        list(agent_scope.evidence_refs) if agent_scope is not None else []
                    ),
                    "untypedSourceReferenceCount": _untyped_ref_count(rows_by_family),
                    "sourceCoverage": source_coverage,
                },
                ("identity", "connection", "interaction", "content", "community", "metric"),
            ),
            "findings": (
                "Observed social relationships and communities",
                connection_items or community_items,
                {
                    "relationships": connection_items,
                    "communityMemberships": community_items,
                    "coverage": source_status,
                    "sourceCoverage": source_coverage,
                },
                ("connection", "community"),
            ),
            "interactions": (
                "Observed interactions and content",
                interaction_items or content_items,
                {"interactions": interaction_items, "content": content_items},
                ("interaction", "content"),
            ),
            "state": (
                "Social identities and measured observations",
                identity_items or metric_items,
                {"identities": identity_items, "metrics": metric_items},
                ("identity", "metric"),
            ),
            "summary": (
                "Social observation summary",
                identity_items
                or connection_items
                or interaction_items
                or content_items
                or community_items
                or metric_items,
                {
                    "identityCount": len(identity_items) if identity_count_known else None,
                    "relationshipCount": len(connection_items)
                    if source_status == "available"
                    else None,
                    "communityMembershipCount": len(community_items)
                    if source_status == "available"
                    else None,
                    "interactionCount": len(interaction_items)
                    if source_status == "available"
                    else None,
                    "contentObservationCount": len(content_items)
                    if source_status == "available"
                    else None,
                    "metricObservationCount": len(metric_items)
                    if source_status == "available"
                    else None,
                    "coverage": source_status,
                    "sourceCoverage": source_coverage,
                    "metricsAreObservedValues": True,
                    "influenceScore": None,
                    "organicClassification": None,
                    "populationScope": (
                        {
                            "state": population_scope.state,
                            "memberCount": len(population_scope.entity_ids),
                            "relationshipScope": "internal_to_verified_population_members",
                        }
                        if population_scope is not None
                        else None
                    ),
                    "sourceIdentityScope": (
                        {
                            "state": source_scope.state,
                            "canonicalEntityId": source_scope.canonical_entity_id,
                        }
                        if source_scope is not None
                        else None
                    ),
                    "agentIdentityScope": (
                        {
                            "state": agent_scope.state,
                            "canonicalAgentEntityId": agent_scope.canonical_agent_entity_id,
                        }
                        if agent_scope is not None
                        else None
                    ),
                },
                _FACT_TABLES,
            ),
            "timeline": (
                "Observed social timeline",
                interaction_items or content_items,
                {
                    "items": sorted(
                        interaction_items
                        + [
                            {**item, "observed_at": item.get("published_at")}
                            for item in content_items
                            if item.get("published_at")
                        ],
                        key=lambda item: str(item.get("observed_at") or ""),
                    ),
                },
                ("interaction", "content"),
            ),
        }

        sections: list[ProjectionSection] = []
        for section_id, (title, rows_or_refs, content_value, families) in section_data.items():
            if section_id not in include:
                continue
            family_reads = [
                reads.get(family, Social360FactRead([], available=False)) for family in families
            ]
            has_rows = bool(rows_or_refs)
            failed = any(not read.available for read in family_reads)
            truncated = any(read.truncated for read in family_reads)
            if (
                failed
                or truncated
                or scope_mismatch
                or identity_scope_incomplete
                or temporal_unknown
            ):
                state = "degraded"
            elif not identity_ids:
                state = "unknown"
            elif has_rows:
                state = "available"
            else:
                state = "empty"
            warnings = []
            warnings.extend(
                f"{family}_source_unavailable"
                for family in families
                if not reads.get(family, Social360FactRead([], available=False)).available
            )
            warnings.extend(
                f"{family}_source_truncated"
                for family in families
                if reads.get(family) and reads[family].truncated
            )
            if not identity_ids:
                warnings.append("canonical_social_identity_binding_unavailable")
            if scope_mismatch:
                warnings.append("social_fact_scope_or_identity_conflict")
            if temporal_unknown:
                warnings.append("temporal_fact_coverage_incomplete")
            sections.append(
                ProjectionSection(
                    id=section_id,
                    state=state,
                    title=title,
                    content=content_value if state in {"available", "degraded", "empty"} else None,
                    warnings=sorted(set(warnings)) or None,
                )
            )

        path_section, path_claims = self._path_section_and_claims(request.subject, path_read)
        if "paths" in include:
            sections.append(path_section)
        propagation_section, propagation_claims = self._propagation_section_and_claims(
            request.subject,
            request.tenantId,
            propagation_read,
            as_of=now,
        )
        if "propagation" in include:
            sections.append(propagation_section)

        claims = self._claims(request.subject, rows_by_family, refs_by_family)
        claims.extend(path_claims)
        if "propagation" in include:
            claims.extend(propagation_claims)
        degraded_reasons = sorted(
            {
                read.reason or f"{family}_source_unavailable"
                for family, read in reads.items()
                if not read.available
            }
            | ({"source_read_capped"} if any(read.truncated for read in reads.values()) else set())
            | ({"social_fact_scope_or_identity_conflict"} if scope_mismatch else set())
            | ({"canonical_social_identity_binding_unavailable"} if not identity_ids else set())
            | ({"temporal_fact_coverage_incomplete"} if temporal_unknown else set())
        )
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            generatedAt=now,
            asOf=(request.asOf or context.asOf) if request.temporalMode == "as_of" else None,
            degradedReasons=degraded_reasons,
            temporalMode=request.temporalMode or "window",
        )

    async def _read_social_paths(self, tenant_id: str, start_entity_id: str) -> SocialGraphPathRead:
        try:
            result = await self._social_graph_paths.read_paths(tenant_id, start_entity_id)
        except Exception:  # noqa: BLE001 - canonical graph authority is fail-closed
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("canonical_social_graph_authority_unavailable",),
            )
        if not isinstance(result, SocialGraphPathRead):
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("invalid_social_graph_path_source_contract",),
            )
        if result.tenant_id != tenant_id or result.start_entity_id != start_entity_id:
            return SocialGraphPathRead(
                tenant_id,
                start_entity_id,
                available=False,
                reason_codes=("canonical_social_path_scope_mismatch",),
            )
        return result

    async def _authorize_social_paths(
        self,
        result: SocialGraphPathRead,
        tenant_id: str,
        start_entity_id: str,
        *,
        already_checked: dict[str, bool],
    ) -> SocialGraphPathRead:
        if not result.available:
            return result
        visible_paths: list[SocialObservedPath] = []
        policy_filtered = False
        invalid_path = False
        consent_by_entity = dict(already_checked)
        for path in result.paths:
            if not _valid_social_observed_path(path, start_entity_id):
                invalid_path = True
                continue
            allowed = True
            for entity_id in path.entity_ids[1:]:
                if entity_id not in consent_by_entity:
                    try:
                        consent = await self._consent_reader(
                            tenant_id, entity_id, None, "analytics"
                        )
                    except Exception:  # noqa: BLE001 - consent is fail-closed
                        consent = (False, "consent_authority_unavailable")
                    consent_by_entity[entity_id] = _consent_allowed(consent)
                if not consent_by_entity[entity_id]:
                    allowed = False
            if allowed:
                visible_paths.append(path)
            else:
                policy_filtered = True

        reasons = set(result.reason_codes)
        if policy_filtered:
            reasons.add("social_path_endpoint_consent_restricted")
        if invalid_path:
            reasons.add("invalid_canonical_social_path_result")
        return SocialGraphPathRead(
            tenant_id,
            start_entity_id,
            paths=tuple(visible_paths),
            available=result.available,
            truncated=result.truncated,
            reason_codes=tuple(sorted(reasons)),
        )

    @staticmethod
    def _path_section_and_claims(
        subject: ProjectionSubject, result: SocialGraphPathRead
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        reasons = list(result.reason_codes)
        claims: list[ClaimEnvelope] = []
        visible_paths = list(result.paths)
        if visible_paths and result.available:
            evidence_refs = _dedupe_refs(
                [ref for path in visible_paths for edge in path.edge_evidence_refs for ref in edge]
            )
            path_items = []
            for path in visible_paths:
                path_refs = [_dedupe_refs(list(edge_refs)) for edge_refs in path.edge_evidence_refs]
                path_items.append(
                    {
                        "entityPath": list(path.entity_ids),
                        "edgePredicate": "FOLLOWS",
                        "edgeEvidenceRefs": path_refs,
                    }
                )
                evidence = _dedupe_refs(
                    [ref for edge_refs in path.edge_evidence_refs for ref in edge_refs]
                )
                path_key = "\x1f".join([*path.entity_ids, *(ref.id for ref in evidence)])
                digest = hashlib.sha256(path_key.encode("utf-8")).hexdigest()[:24]
                claims.append(
                    ClaimEnvelope(
                        id=f"social360.multi_hop_paths.{digest}",
                        kind="social_follows_path_observation",
                        subject=subject,
                        evidenceRefs=evidence,
                        claims=[
                            "The tenant-scoped canonical graph records this directed sequence "
                            "of FOLLOWS edges as separate observed relationships; no transitive "
                            "relationship, trust, or influence is asserted."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["multi_hop_paths"],
                    )
                )

            state = "degraded" if result.truncated or reasons else "available"
            content = {
                "multiHopPaths": {
                    "state": state,
                    "paths": path_items,
                    "coverage": "bounded_observed_paths_only",
                    "completeness": "unknown",
                    "freshness": "unknown",
                    "pathDepthLimit": _SOCIAL_PATH_DEPTH,
                    "minimumHops": 2,
                    "pathSemantics": {
                        "edgePredicate": "FOLLOWS",
                        "directedObservedEdges": True,
                        "transitiveRelationshipClaim": False,
                        "trustInferred": False,
                        "influenceInferred": False,
                    },
                    "evidenceRefs": evidence_refs,
                }
            }
            return (
                ProjectionSection(
                    id="paths",
                    state=state,
                    title="Bounded observed FOLLOWS paths",
                    content=content,
                    warnings=reasons or None,
                    canonicalAuthorityRefs=list(_SOCIAL_PATH_AUTHORITIES),
                ),
                claims,
            )

        if not reasons:
            reasons = ["no_bounded_observed_follows_paths"]
        unsupported_temporal = "social_graph_path_temporal_scope_unsupported" in reasons
        unsupported_subject = "multi_hop_paths_entity_subject_required" in reasons
        unavailable = not result.available and not (unsupported_temporal or unsupported_subject)
        state = "degraded" if unavailable or result.truncated else "unknown"
        return (
            ProjectionSection(
                id="paths",
                state=state,
                title="Bounded observed FOLLOWS paths",
                content=None,
                warnings=sorted(set(reasons)),
                canonicalAuthorityRefs=list(_SOCIAL_PATH_AUTHORITIES),
            ),
            claims,
        )

    @staticmethod
    def _propagation_section_and_claims(
        subject: ProjectionSubject,
        tenant_id: str,
        result: SocialGraphPathRead,
        *,
        as_of: str,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Expose only registry-authorized observed paths as propagation context.

        The canonical influence-propagation substrate certifies whether the
        registered predicates permit a path to carry propagation semantics.
        This provider deliberately supplies no M7 measurements, so it emits
        component coverage only (never values or a contagion conclusion).
        """
        from shared.relationship_spine.influence_propagation import (
            decompose_influence_propagation,
        )

        reasons = set(result.reason_codes)
        path_items: list[dict[str, Any]] = []
        claims: list[ClaimEnvelope] = []
        saw_invalid_path = False
        for path in result.paths:
            if not _valid_social_propagation_path(
                path, tenant_id, result.start_entity_id, as_of=as_of
            ):
                saw_invalid_path = True
                continue

            decomposition = decompose_influence_propagation(
                list(path.graph_edges),
                source_ref=path.entity_ids[0],
                target_ref=path.entity_ids[-1],
                as_of=as_of,
            )
            edge_times = list(path.edge_observed_at)
            parsed_times = [_parse_graph_time(value) for value in edge_times]
            if any(value is None for value in parsed_times):
                time_order_state = "unknown"
                reasons.add("social_propagation_source_observation_time_missing")
            elif parsed_times == sorted(parsed_times):
                time_order_state = "ordered"
            else:
                time_order_state = "conflicted"
                reasons.add("social_propagation_source_observation_order_conflicted")

            component_coverage = [
                {
                    "componentId": component.component_id,
                    "state": component.state,
                    "reasonCode": component.reason_code or None,
                    "measuredHopCount": component.measured_hops,
                    "materialHopCount": component.material_hops,
                }
                for component in decomposition.all_components
            ]
            if not decomposition.available_component_ids:
                reasons.add("social_propagation_components_unmeasured")
            if not decomposition.propagation_certified:
                reasons.update(decomposition.reason_codes)

            edge_refs = [
                _dedupe_refs(list(refs)) for refs in path.edge_evidence_refs
            ]
            evidence_refs = _dedupe_refs(
                [ref for refs in path.edge_evidence_refs for ref in refs]
            )
            path_items.append(
                {
                    "entityPath": list(path.entity_ids),
                    "edgePredicate": "FOLLOWS",
                    "edgeEvidenceRefs": edge_refs,
                    "sourceObservedAtByEdge": edge_times,
                    "timeOrderState": time_order_state,
                    "propagationAuthority": {
                        "decision": decomposition.decision,
                        "certifiedForPropagationAnalysis": decomposition.propagation_certified,
                        "reasonCodes": list(decomposition.reason_codes),
                        "hopCount": decomposition.hop_count,
                        "epistemicCeiling": decomposition.min_epistemic_ceiling,
                        "staleness": decomposition.staleness_status,
                    },
                    "componentCoverage": component_coverage,
                    "evidenceRefs": evidence_refs,
                }
            )
            if decomposition.propagation_certified:
                digest_basis = "\x1f".join(
                    [*path.entity_ids, *(ref.id for ref in evidence_refs)]
                )
                digest = hashlib.sha256(digest_basis.encode("utf-8")).hexdigest()[:24]
                claims.append(
                    ClaimEnvelope(
                        id=f"social360.propagation_path.{digest}",
                        kind="social_propagation_path_observation",
                        subject=subject,
                        evidenceRefs=evidence_refs,
                        claims=[
                            "The tenant-scoped graph records this directed sequence of "
                            "FOLLOWS relationships, and the governed predicate registry "
                            "permits propagation analysis on the path. This does not "
                            "establish that behavior, trust, risk, influence, or an outcome "
                            "propagated."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["propagation"],
                    )
                )

        if saw_invalid_path:
            reasons.add("canonical_social_propagation_path_validation_failed")
        if path_items:
            reasons.add("social_propagation_component_measurements_unavailable")
            state = "degraded"
            content: Optional[dict[str, Any]] = {
                "propagation": {
                    "state": state,
                    "paths": path_items,
                    "coverage": "bounded_observed_propagation_eligible_paths",
                    "completeness": "unknown",
                    "freshness": "unknown",
                    "componentValuesIncluded": False,
                    "causalContagionEstablished": False,
                    "evidenceRefs": _dedupe_refs(
                        [ref for item in path_items for ref in item["evidenceRefs"]]
                    ),
                }
            }
        else:
            content = None
            unsupported_scope = any(
                code in reasons
                for code in {
                    "social_propagation_subject_scope_unavailable",
                    "social_propagation_entity_or_relationship_subject_required",
                    "social_propagation_temporal_scope_unsupported",
                }
            )
            unavailable = not result.available and not unsupported_scope
            if not reasons:
                reasons.add("no_bounded_observed_propagation_paths")
            state = "degraded" if unavailable or result.truncated or saw_invalid_path else "unknown"

        return (
            ProjectionSection(
                id="propagation",
                state=state,
                title="Observed propagation-eligible social paths",
                content=content,
                warnings=sorted(reasons) or None,
                canonicalAuthorityRefs=list(_SOCIAL_PROPAGATION_AUTHORITIES),
            ),
            claims,
        )

    async def _read(self, family: str, tenant_id: str) -> Social360FactRead:
        try:
            result = await self._source.read(family, tenant_id, limit=_MAX_READ_ROWS)
        except Exception:  # noqa: BLE001 - authority failures are section degradation
            return Social360FactRead(
                rows=[], available=False, reason=f"{family}_source_unavailable"
            )
        if not isinstance(result, Social360FactRead):
            return Social360FactRead(rows=[], available=False, reason="invalid_source_contract")
        return result

    @staticmethod
    def _claims(
        subject: ProjectionSubject,
        rows_by_family: dict[str, list[dict[str, Any]]],
        refs_by_family: dict[str, list[EvidenceRef]],
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for family, rows in rows_by_family.items():
            domain_slot_ids = _domain_slot_ids(subject.kind, family)
            if not domain_slot_ids:
                continue
            refs_by_id = {ref.id: ref for ref in refs_by_family.get(family, [])}
            table = f"silver_social_{family}_facts"
            for row in rows:
                ref = refs_by_id.get(_text(row.get("fact_id")) or "")
                if ref is None:
                    continue
                claims.append(
                    ClaimEnvelope(
                        id=f"social360.{family}.{ref.id}",
                        kind=f"social_{family}_fact_observation",
                        subject=subject,
                        evidenceRefs=[ref],
                        claims=[
                            f"A tenant-scoped {table} row records a social {family} observation."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=domain_slot_ids,
                    )
                )
        return claims

    @staticmethod
    def _empty_population_result(
        request: ProjectionRequest,
        context: ProjectionContext,
        generated_at: str,
        scope: PopulationScopeRead,
    ) -> ProjectionResult:
        """Return a known-empty social view when a verified population has no members."""
        membership_refs = list(scope.evidence_refs)
        empty_content = {
            "evidence": {
                "evidenceRefs": membership_refs,
                "populationMembershipEvidenceRefs": membership_refs,
                "coverage": "empty_population",
            },
            "findings": {
                "relationships": [],
                "communityMemberships": [],
                "coverage": "empty_population",
            },
            "interactions": {"interactions": [], "content": []},
            "state": {"identities": [], "metrics": []},
            "summary": {
                "identityCount": 0,
                "relationshipCount": 0,
                "communityMembershipCount": 0,
                "interactionCount": 0,
                "contentObservationCount": 0,
                "metricObservationCount": 0,
                "coverage": "empty_population",
                "metricsAreObservedValues": True,
                "influenceScore": None,
                "organicClassification": None,
                "populationScope": {
                    "state": "empty",
                    "memberCount": 0,
                    "relationshipScope": "internal_to_verified_population_members",
                },
            },
            "timeline": {"items": []},
        }
        include = set(request.includeSections or OUTPUT_SECTIONS)
        sections = []
        for section_id in OUTPUT_SECTIONS:
            if section_id not in include:
                continue
            if section_id == "paths":
                sections.append(
                    ProjectionSection(
                        id="paths",
                        state="unknown",
                        title="Bounded observed FOLLOWS paths",
                        warnings=["multi_hop_paths_entity_subject_required"],
                        canonicalAuthorityRefs=list(_SOCIAL_PATH_AUTHORITIES),
                    )
                )
                continue
            if section_id == "propagation":
                sections.append(
                    ProjectionSection(
                        id="propagation",
                        state="unknown",
                        title="Observed propagation-eligible social paths",
                        warnings=["empty_population_has_no_path_scope"],
                        canonicalAuthorityRefs=list(_SOCIAL_PROPAGATION_AUTHORITIES),
                    )
                )
                continue
            sections.append(
                ProjectionSection(
                    id=section_id,
                    state="empty",
                    title="Social observation population view",
                    content=empty_content[section_id],
                )
            )
        return ProjectionResult(
            projectionId=PROJECTION_ID,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=generated_at,
            degradedReasons=[],
            temporalMode=request.temporalMode or "window",
        )

    def _unknown_result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        generated_at: str,
        reason: str,
        *,
        subject: ProjectionSubject,
    ) -> ProjectionResult:
        include = set(request.includeSections or OUTPUT_SECTIONS)
        sections = [
            ProjectionSection(
                id=section_id,
                state="unknown",
                warnings=[reason],
                canonicalAuthorityRefs=(
                    list(_SOCIAL_PATH_AUTHORITIES)
                    if section_id == "paths"
                    else list(_SOCIAL_PROPAGATION_AUTHORITIES)
                    if section_id == "propagation"
                    else None
                ),
            )
            for section_id in OUTPUT_SECTIONS
            if section_id in include
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=context.dependencyState,
            generatedAt=generated_at,
            degradedReasons=[reason],
        )

    def _suppressed_result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        generated_at: str,
        reason: str,
        *,
        subject: ProjectionSubject,
    ) -> ProjectionResult:
        include = set(request.includeSections or OUTPUT_SECTIONS)
        sections = [
            ProjectionSection(
                id=section_id,
                state="suppressed",
                warnings=[reason],
                canonicalAuthorityRefs=(
                    list(_SOCIAL_PATH_AUTHORITIES)
                    if section_id == "paths"
                    else list(_SOCIAL_PROPAGATION_AUTHORITIES)
                    if section_id == "propagation"
                    else None
                ),
            )
            for section_id in OUTPUT_SECTIONS
            if section_id in include
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=context.dependencyState,
            generatedAt=generated_at,
            degradedReasons=[reason],
        )


def _subject_endpoints(subject: ProjectionSubject) -> Optional[tuple[str, ...]]:
    if subject.kind in {"entity", "source"}:
        return (subject.id,)
    if subject.kind == "relationship":
        source, delimiter, target = subject.id.partition("::")
        if (
            delimiter
            and source.strip()
            and target.strip()
            and "::" not in target
            and source != target
        ):
            return source, target
    return None


def _consent_allowed(result: Any) -> bool:
    if isinstance(result, tuple) and result:
        return result[0] is True
    return getattr(result, "allowed", False) is True


def _text(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _truthy_marker(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "revoked"}
    return False


def _parse_graph_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _graph_evidence_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(text for item in value if (text := _text(item))))


def _valid_social_observed_path(path: Any, start_entity_id: str) -> bool:
    if not isinstance(path, SocialObservedPath):
        return False
    if not (3 <= len(path.entity_ids) <= _SOCIAL_PATH_DEPTH + 1):
        return False
    if path.entity_ids[0] != start_entity_id:
        return False
    if any(not _text(entity_id) for entity_id in path.entity_ids):
        return False
    if len(set(path.entity_ids)) != len(path.entity_ids):
        return False
    if len(path.edge_evidence_refs) != len(path.entity_ids) - 1:
        return False
    return all(
        edge_refs and all(isinstance(ref, EvidenceRef) and _text(ref.id) for ref in edge_refs)
        for edge_refs in path.edge_evidence_refs
    )


def _valid_social_propagation_path(
    path: Any, tenant_id: str, start_entity_id: str, *, as_of: str
) -> bool:
    """Validate the exact graph hops and evidence before propagation analysis."""
    from shared.graph.graph import tenant_of

    if not _valid_social_observed_path(path, start_entity_id):
        return False
    edge_count = len(path.entity_ids) - 1
    if len(path.graph_edges) != edge_count or len(path.edge_observed_at) != edge_count:
        return False

    reference = _parse_graph_time(as_of)
    if reference is None:
        return False
    for index, edge in enumerate(path.graph_edges):
        edge_type = (
            edge.get("edge_type") or edge.get("type")
            if isinstance(edge, dict)
            else getattr(edge, "edge_type", None)
        )
        from_id = (
            edge.get("from_vertex_id") or edge.get("from")
            if isinstance(edge, dict)
            else getattr(edge, "from_vertex_id", None)
        )
        to_id = (
            edge.get("to_vertex_id") or edge.get("to")
            if isinstance(edge, dict)
            else getattr(edge, "to_vertex_id", None)
        )
        properties = (
            edge.get("properties") or {}
            if isinstance(edge, dict)
            else getattr(edge, "properties", None) or {}
        )
        if not isinstance(properties, dict):
            return False
        if (
            edge_type != "FOLLOWS_SOCIAL"
            or from_id != path.entity_ids[index]
            or to_id != path.entity_ids[index + 1]
            or tenant_of(properties) != tenant_id
            or properties.get("relationship_predicate") != "FOLLOWS"
            or _truthy_marker(properties.get("revoked"))
            or bool(properties.get("revoked_at"))
        ):
            return False

        valid_from_value = properties.get("valid_from")
        valid_to_value = properties.get("valid_to")
        valid_from = _parse_graph_time(valid_from_value) if valid_from_value else None
        valid_to = _parse_graph_time(valid_to_value) if valid_to_value else None
        if (valid_from_value and valid_from is None) or (valid_to_value and valid_to is None):
            return False
        if valid_from is not None and valid_from > reference:
            return False
        if valid_to is not None and valid_to <= reference:
            return False

        idempotency_key = _text(properties.get("idempotency_key"))
        evidence_ids = set(_graph_evidence_ids(properties.get("evidence_refs")))
        edge_refs = path.edge_evidence_refs[index]
        graph_ref_ids = {
            ref.id for ref in edge_refs if ref.source == "entity_graph" and _text(ref.id)
        }
        fact_ref_ids = {
            ref.id for ref in edge_refs if ref.source == "relationship_facts" and _text(ref.id)
        }
        if not idempotency_key or idempotency_key not in graph_ref_ids or evidence_ids != fact_ref_ids:
            return False

        observed_at = _parse_graph_time(properties.get("observed_at"))
        expected_observed_at = observed_at.isoformat() if observed_at is not None else None
        if path.edge_observed_at[index] != expected_observed_at:
            return False
    return True


def _tenant_rows(read: Social360FactRead, tenant_id: str) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    mismatch = False
    for row in read.rows:
        if not isinstance(row, dict) or row.get("tenant_id") != tenant_id:
            mismatch = True
            continue
        rows.append(row)
    return rows, mismatch


def _unique_identity_ids(
    all_rows: list[dict[str, Any]], subject_entities: set[str]
) -> tuple[set[str], set[str]]:
    entity_by_identity: dict[str, set[str]] = {}
    unresolved_identity_ids: set[str] = set()
    for row in all_rows:
        identity_id = _text(row.get("social_identity_id"))
        entity_id = _text(row.get("canonical_entity_ref"))
        if not identity_id:
            continue
        if entity_id:
            entity_by_identity.setdefault(identity_id, set()).add(entity_id)
        else:
            # An unresolved duplicate cannot be ignored when another row binds
            # the same social identity. Its canonical entity may be unknown.
            unresolved_identity_ids.add(identity_id)
    ambiguous = {
        identity_id
        for identity_id, entity_ids in entity_by_identity.items()
        if len(entity_ids) > 1 or identity_id in unresolved_identity_ids
    }
    scoped = {
        identity_id
        for identity_id, entity_ids in entity_by_identity.items()
        if entity_ids.issubset(subject_entities) and identity_id not in ambiguous
    }
    return scoped, ambiguous.intersection(
        identity_id
        for identity_id, entity_ids in entity_by_identity.items()
        if entity_ids.intersection(subject_entities)
    )


def _identity_ids_by_entity(
    identities: list[dict[str, Any]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in identities:
        entity_id = _text(row.get("canonical_entity_ref"))
        identity_id = _text(row.get("social_identity_id"))
        if entity_id and identity_id:
            result.setdefault(entity_id, set()).add(identity_id)
    return result


def _subject_rows(
    family: str,
    rows: list[dict[str, Any]],
    subject: ProjectionSubject,
    identity_ids: set[str],
    identity_ids_by_entity: dict[str, set[str]],
    *,
    population_entity_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    if subject.kind in {"entity", "source", "agent"}:
        return [row for row in rows if _row_mentions_identity(family, row, identity_ids)]
    if subject.kind == "population":
        if population_entity_ids is None:
            return []
        if family in {"connection", "interaction"}:
            left_field, right_field = (
                ("source_social_identity_ref", "target_social_identity_ref")
                if family == "connection"
                else ("actor_social_identity_ref", "target_social_identity_ref")
            )
            return [
                row
                for row in rows
                if _text(row.get(left_field)) in identity_ids
                and _text(row.get(right_field)) in identity_ids
            ]
        return [row for row in rows if _row_mentions_identity(family, row, identity_ids)]
    endpoints = _subject_endpoints(subject)
    if endpoints is None or len(endpoints) != 2:
        return []
    left_ids = identity_ids_by_entity.get(endpoints[0], set())
    right_ids = identity_ids_by_entity.get(endpoints[1], set())
    if not left_ids or not right_ids:
        return []
    selected: list[dict[str, Any]] = []
    for row in rows:
        if family == "connection":
            left = _text(row.get("source_social_identity_ref"))
            right = _text(row.get("target_social_identity_ref"))
            matches = (left in left_ids and right in right_ids) or (
                left in right_ids and right in left_ids
            )
        elif family == "interaction":
            left = _text(row.get("actor_social_identity_ref"))
            right = _text(row.get("target_social_identity_ref"))
            matches = (left in left_ids and right in right_ids) or (
                left in right_ids and right in left_ids
            )
        else:
            matches = _row_mentions_identity(family, row, identity_ids)
        if matches:
            selected.append(row)
    return selected


def _row_mentions_identity(family: str, row: dict[str, Any], identity_ids: set[str]) -> bool:
    columns = {
        "connection": ("source_social_identity_ref", "target_social_identity_ref"),
        "interaction": ("actor_social_identity_ref", "target_social_identity_ref"),
        "content": ("author_social_identity_ref",),
        "community": ("social_identity_ref",),
        "metric": ("social_identity_ref",),
    }.get(family, ())
    return any(_text(row.get(column)) in identity_ids for column in columns)


def _visible_items(
    rows: list[dict[str, Any]], table: str, fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        # Preserve explicit nulls for observations such as an unavailable
        # metric; omission and an observed null are different source states.
        item = {key: row.get(key) for key in fields if key in row}
        reference = _row_evidence(row, table)
        if reference is not None:
            item["evidenceRefs"] = [reference]
        items.append(item)
    return items


def _row_evidence(row: dict[str, Any], table: str) -> Optional[EvidenceRef]:
    fact_id = _text(row.get("fact_id"))
    if not fact_id:
        return None
    observed_at = (
        _text(row.get("received_at"))
        or _text(row.get("observed_at"))
        or _text(row.get("occurred_at"))
        or _text(row.get("published_at"))
    )
    return EvidenceRef(
        id=fact_id,
        type="event",
        source=f"services/api/ingestion/silver/{table}",
        observedAt=observed_at,
        uri=f"store://{table}/{fact_id}",
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    unique: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _untyped_ref_count(rows_by_family: dict[str, list[dict[str, Any]]]) -> int:
    count = 0
    for rows in rows_by_family.values():
        for row in rows:
            for field in ("identity_evidence_refs", "evidence_refs", "contradictory_evidence_refs"):
                refs = row.get(field)
                if isinstance(refs, list):
                    count += sum(isinstance(ref, str) for ref in refs)
    return count


def _source_status(reads: dict[str, Social360FactRead], *, families: tuple[str, ...]) -> str:
    selected = [reads.get(family) for family in families]
    if any(read is None or not read.available for read in selected):
        return "unavailable"
    if any(read and read.truncated for read in selected):
        return "truncated"
    return "available"


_SOURCE_OBSERVATION_TIME_FIELDS: dict[str, tuple[str, ...]] = {
    "identity": ("last_observed_at", "observed_at", "first_observed_at"),
    "connection": ("observed_at",),
    "interaction": ("observed_at", "occurred_at"),
    "content": ("edited_at", "published_at"),
    "community": ("observed_at", "valid_from"),
    "metric": ("observed_at",),
}


def _identity_binding_state(
    read: Social360FactRead,
    identity_ids: set[str],
    ambiguous_identity_ids: set[str],
    bad_identity_scope: bool,
) -> str:
    if not read.available:
        return "unavailable"
    if read.truncated:
        return "truncated"
    if bad_identity_scope or ambiguous_identity_ids:
        return "degraded"
    return "available" if identity_ids else "unresolved"


def _source_coverage(
    reads: dict[str, Social360FactRead],
    rows_by_family: dict[str, list[dict[str, Any]]],
    *,
    queried_families: set[str],
    overall_state: str,
    identity_binding_state: str,
    scope_mismatch: bool,
    temporal_unknown: bool,
    temporal_bounded: bool,
) -> dict[str, Any]:
    """Report subject-scoped Silver coverage without treating skipped reads as empty."""
    families: dict[str, dict[str, Any]] = {}
    for family in _FACT_TABLES:
        read = reads.get(family)
        if family not in queried_families:
            read_state = "not_read"
            reason = "canonical_social_identity_binding_not_established"
            scoped_rows: Optional[list[dict[str, Any]]] = None
        elif read is None or not read.available:
            read_state = "unavailable"
            reason = read.reason if read is not None else f"{family}_source_unavailable"
            scoped_rows = None
        elif read.truncated:
            read_state = "truncated"
            reason = read.reason or "source_read_capped"
            scoped_rows = rows_by_family.get(family, [])
        else:
            read_state = "available"
            reason = None
            scoped_rows = rows_by_family.get(family, [])

        if scoped_rows is None:
            source_times = None
            received_times = None
            scoped_count = None
        else:
            source_times = [
                value
                for row in scoped_rows
                if (value := _source_observed_time(family, row)) is not None
            ]
            received_times = [
                value
                for row in scoped_rows
                if (value := _parse_time(_text(row.get("received_at")))) is not None
            ]
            scoped_count = len(scoped_rows)

        families[family] = {
            "readState": read_state,
            "reason": reason,
            "scopedObservationCount": scoped_count,
            "sourceTimestampedCount": len(source_times) if source_times is not None else None,
            "sourceTimestampMissingCount": (
                scoped_count - len(source_times)
                if scoped_count is not None and source_times is not None
                else None
            ),
            "latestSourceObservedAt": (max(source_times).isoformat() if source_times else None),
            "receivedAtCount": len(received_times) if received_times is not None else None,
            "receivedAtMissingCount": (
                scoped_count - len(received_times)
                if scoped_count is not None and received_times is not None
                else None
            ),
        }

    return {
        "state": overall_state,
        "identityBindingState": identity_binding_state,
        "scopeState": (
            "degraded"
            if scope_mismatch or identity_binding_state in {"unavailable", "truncated", "degraded"}
            else "unknown"
            if identity_binding_state == "unresolved"
            else "available"
        ),
        "temporalScopeState": (
            "incomplete"
            if temporal_unknown
            else "complete"
            if temporal_bounded
            else "not_requested"
        ),
        "temporalScope": "bounded" if temporal_bounded else "unbounded",
        "countsAreScopedToRequestedSubject": True,
        "sourceTimestamps": "preserved_when_present",
        "missingTimestamp": "unknown",
        "families": families,
    }


def _source_observed_time(family: str, row: dict[str, Any]) -> Optional[datetime]:
    for field in _SOURCE_OBSERVATION_TIME_FIELDS[family]:
        parsed = _parse_time(_text(row.get(field)))
        if parsed is not None:
            return parsed
    return None


def _filter_temporal(
    rows: list[dict[str, Any]], request: ProjectionRequest, context_anchor: Optional[str]
) -> tuple[list[dict[str, Any]], bool]:
    mode = request.temporalMode or "window"
    start_raw = request.timeRange.from_ if request.timeRange else None
    end_raw = request.timeRange.to if request.timeRange else None
    anchor_raw = request.asOf or context_anchor

    start = _parse_time(start_raw)
    end = _parse_time(end_raw)
    anchor = _parse_time(anchor_raw)
    has_window = start_raw is not None or end_raw is not None
    if mode == "as_of" and anchor is None:
        return [], True
    if mode == "relative" and not has_window:
        return [], True
    if (start_raw is not None and start is None) or (end_raw is not None and end is None):
        return [], True
    if not has_window and mode != "as_of":
        return rows, False

    filtered: list[dict[str, Any]] = []
    unknown = False
    for row in rows:
        time_value = (
            row.get("received_at")
            if mode == "as_of"
            else row.get("observed_at") or row.get("occurred_at") or row.get("published_at")
        )
        observed = _parse_time(_text(time_value))
        if observed is None:
            unknown = True
            continue
        if mode == "as_of":
            if anchor is not None and observed <= anchor:
                filtered.append(row)
            continue
        if start is not None and observed < start:
            continue
        if end is not None and observed > end:
            continue
        filtered.append(row)
    return filtered, unknown


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


_SUPPORTED_SLOTS_BY_FAMILY: dict[str, frozenset[str]] = {
    # Every direct Silver claim remains an observation and carries an EvidenceRef.
    # Optional, more specific slots are earned only by the relevant source family.
    "identity": frozenset(
        {"social_observations_and_sources", "evidence_and_coverage", "evidence_trace"}
    ),
    "connection": frozenset(
        {
            "social_observations_and_sources",
            "evidence_and_coverage",
            "evidence_trace",
            # A provider-recorded connection may populate a relationship map
            # as source evidence, but does not become a canonical graph edge.
            "relationship_map",
        }
    ),
    "interaction": frozenset(
        {"social_observations_and_sources", "evidence_and_coverage", "evidence_trace"}
    ),
    "content": frozenset(
        {"social_observations_and_sources", "evidence_and_coverage", "evidence_trace"}
    ),
    "community": frozenset(
        {
            "social_observations_and_sources",
            "evidence_and_coverage",
            "evidence_trace",
            # This slot is limited to recorded membership facts, not syndicate
            # or contagion synthesis.
            "communities",
        }
    ),
    "metric": frozenset(
        {"social_observations_and_sources", "evidence_and_coverage", "evidence_trace"}
    ),
}


def _domain_slot_ids(subject_kind: str, fact_family: str) -> list[str]:
    result: set[str] = set()
    supported_slots = _SUPPORTED_SLOTS_BY_FAMILY.get(fact_family, frozenset())
    for surface_id, surface in PRODUCT_360_SURFACE_DEFINITIONS.items():
        # These are direct Social360 fact claims. Other surfaces may bind the
        # projection as supporting evidence, but that does not make every
        # social fact a risk, fraud, or contagion claim.
        if surface_id != "social360":
            continue
        if not isinstance(surface, dict):
            continue
        for slot in surface.get("domainSlots", []):
            if not isinstance(slot, dict):
                continue
            for binding in slot.get("projectionBindings", []):
                if (
                    isinstance(binding, dict)
                    and binding.get("projectionId") == PROJECTION_ID
                    and subject_kind in binding.get("subjectKinds", [])
                    and isinstance(slot.get("id"), str)
                    and slot["id"] in supported_slots
                ):
                    result.add(slot["id"])
    return sorted(result)


def register_provider(registry: ProviderRegistry) -> str:
    return registry.register(Social360Provider(), source="social_silver")


__all__ = [
    "AgentSubjectScopeRead",
    "AgentSubjectScopeReader",
    "RepositorySocial360Source",
    "RepositoryAgentSubjectScopeReader",
    "Social360FactRead",
    "Social360Provider",
    "Social360Source",
    "register_provider",
]
