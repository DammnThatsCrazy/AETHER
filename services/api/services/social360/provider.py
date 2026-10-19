"""Tenant-scoped Social360 projection over canonical Social Silver facts.

This projection reports persisted social observations. It does not derive a
universal influence score, promote observations into graph relationships, or
turn unavailable coverage into zero. Relationship subjects use the canonical
``source_entity::target_entity`` pair form shared with Relationship360 and only
surface Social Silver facts that are bound to those exact endpoints.
"""

from __future__ import annotations

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
    "state",
    "summary",
    "timeline",
)
_MAX_READ_ROWS = 500
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

        reads: dict[str, Social360FactRead] = {}
        reads["identity"] = await self._read("identity", request.tenantId)
        tenant_identity_rows, bad_identity_scope = _tenant_rows(reads["identity"], request.tenantId)
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
        if identity_ids:
            for family in _FACT_TABLES[1:]:
                reads[family] = await self._read(family, request.tenantId)
                rows, bad_scope = _tenant_rows(reads[family], request.tenantId)
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
        if not identity_ids:
            source_status = "unresolved"
        if scope_mismatch or temporal_unknown:
            source_status = "degraded" if source_status in {"available", "empty"} else source_status

        identity_count_known = bool(identity_ids) and not reads["identity"].truncated
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

        include = set(request.includeSections or OUTPUT_SECTIONS)
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
            if has_rows:
                state = (
                    "degraded"
                    if failed or truncated or scope_mismatch or temporal_unknown
                    else "available"
                )
            elif not identity_ids:
                state = "unknown"
            elif failed or truncated or temporal_unknown:
                state = "unknown"
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

        claims = self._claims(request.subject, rows_by_family, refs_by_family)
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
        domain_slot_ids = _domain_slot_ids(subject.kind)
        if not domain_slot_ids:
            return []
        claims: list[ClaimEnvelope] = []
        for family, rows in rows_by_family.items():
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
        sections = [
            ProjectionSection(
                id=section_id,
                state="empty",
                title="Social observation population view",
                content=empty_content[section_id],
            )
            for section_id in OUTPUT_SECTIONS
            if section_id in include
        ]
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
            ProjectionSection(id=section_id, state="unknown", warnings=[reason])
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
            ProjectionSection(id=section_id, state="suppressed", warnings=[reason])
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
    for row in all_rows:
        identity_id = _text(row.get("social_identity_id"))
        entity_id = _text(row.get("canonical_entity_ref"))
        if identity_id and entity_id:
            entity_by_identity.setdefault(identity_id, set()).add(entity_id)
    ambiguous = {
        identity_id for identity_id, entity_ids in entity_by_identity.items() if len(entity_ids) > 1
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


def _domain_slot_ids(subject_kind: str) -> list[str]:
    result: set[str] = set()
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
