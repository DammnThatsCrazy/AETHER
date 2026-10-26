"""Shared intelligence-projection request/context/result contracts (P0.4).

Python twin of ``packages/shared/intelligence-projection.ts``. A 360 is an
intelligence projection over canonical Aether truth — never a competing system
of record. These models are the stable boundary the projection runtime (P0.5)
and future 360 providers implement against.

Reuse, never redefine: ``ContractModel``, ``EvidenceRef``, ``PageRequest``,
``PageInfo`` and ``TimeRangeFilter`` are the canonical operational-intelligence
primitives imported from ``services/api/graph/operational_intelligence/models.py``
(single-monolith reuse). The ``SectionState`` / ``ProjectionId`` /
``ProjectionSubjectKind`` / ``ProjectionRegistryState`` vocabularies are derived
from the generated registry (``shared/intelligence_projections/generated_registry.py``)
so the typed vocabulary can never drift from the canonical JSON.

All models inherit :class:`ProjectionContract` (``extra="forbid"``) so a
misspelled field raises instead of silently passing — the canonical primitives
(``ContractModel``) stay tolerant, the projection plane fails closed.

Timestamp convention: ``asOf`` / ``generatedAt`` are ISO-8601 UTC strings,
matching the repo's operational-intelligence models (e.g. ``computedAt``).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, Field, model_validator

# Generated registry vocab — never hand-maintained here (derived below).
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_IMPLEMENTATION_STATES,
    PROJECTION_SECTION_STATES,
    PROJECTION_SUBJECT_KINDS,
)
from shared.intelligence_projections import generated_registry as _generated_registry

# Consolidated claim-state authority (single vocabulary claims render against).
from shared.contracts_models.epistemic import EpistemicStatus

# Reused canonical primitives (single-monolith reuse — never redefined here).
from graph.operational_intelligence.models import (
    ContractModel,
    ActorKind,
    EvidenceRef,
    PageInfo,
    PageRequest,
    TimeRangeFilter,
)

# Deriving typing.Literal from the generated tuples keeps the vocabulary in
# lockstep with the registry JSON (the TS twin derives the same unions from
# `typeof intelligenceProjectionSectionStates[number]` & friends).
SectionState = Literal[tuple(PROJECTION_SECTION_STATES)]
ProjectionId = Literal[tuple(INTELLIGENCE_PROJECTION_IDS)]
ProjectionRegistryState = Literal[tuple(PROJECTION_IMPLEMENTATION_STATES)]

# Union of every subject kind the registry declares (top-level vocab). Distinct
# from EntityKind by design: projections are asked about campaigns, episodes,
# populations, sources, connections, clusters and relationships too.
ProjectionSubjectKind = Literal[tuple(PROJECTION_SUBJECT_KINDS)]

# The 18-product-surface catalog is generated from the same canonical
# projection-registry JSON, but is being introduced alongside these contracts.
# Keep imports usable while that generated artifact is refreshed. Once present,
# the runtime values below become the exact static Literal vocabularies used by
# Pydantic/OpenAPI. The fallback state tuple matches the catalog's initial
# contract and is replaced by its generated tuple at import time.
PRODUCT_360_SURFACE_IDS = tuple(getattr(_generated_registry, "PRODUCT_360_SURFACE_IDS", ()))
EXPERIENCE_360_FRAME_STATES = tuple(
    getattr(
        _generated_registry,
        "EXPERIENCE_360_FRAME_STATES",
        (
            "ready",
            "partial",
            "empty",
            "missing",
            "unknown",
            "suppressed",
            "stale",
            "degraded",
            "unavailable",
            "conflicted",
        ),
    )
)

Experience360SurfaceId = Literal[tuple(PRODUCT_360_SURFACE_IDS)] if PRODUCT_360_SURFACE_IDS else str
Experience360FrameState = Literal[tuple(EXPERIENCE_360_FRAME_STATES)]
Experience360SlotState = Literal[
    tuple(dict.fromkeys((*PROJECTION_SECTION_STATES, "conflicted", "unresolved", "truncated")))
]


class ProjectionContract(ContractModel):
    """Projection-plane contract base — fails closed on unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ProjectionSubject(ProjectionContract):
    """The subject a projection is asked about.

    ``kind`` is the projection-plane subject vocabulary derived from the
    generated registry — intentionally broader than ``EntityRef.kind``.
    """

    kind: ProjectionSubjectKind
    id: str


class ProjectionRequest(ProjectionContract):
    """Request to run an intelligence projection over canonical Aether truth.

    ``lensIds`` / ``temporalMode`` are projection-engine (A8) extensions,
    strictly OPTIONAL so a minimal construction remains valid and providers
    that do not yet understand lenses ignore them. ``temporalMode`` carries a
    registry-surface temporal mode (``window`` / ``as_of`` / ``compare`` /
    ``relative``); the richer engine-level ``TemporalMode`` enum dispatches
    onto these four surface modes and never leaks into the wire contract.
    """

    projectionId: ProjectionId
    tenantId: str
    subject: ProjectionSubject
    page: Optional[PageRequest] = None
    timeRange: Optional[TimeRangeFilter] = None
    # Exact point-in-time anchor. Providers that cannot honor it must leave
    # result.asOf absent or report their effective anchor; frame composition
    # will suppress content whose result does not match this request.
    asOf: Optional[str] = None
    includeSections: Optional[list[str]] = None
    includeClaims: Optional[bool] = None
    lensIds: Optional[list[str]] = None
    temporalMode: Optional[str] = None

    @model_validator(mode="after")
    def validate_as_of_anchor(self) -> "ProjectionRequest":
        if self.asOf is not None:
            from datetime import datetime

            try:
                anchor = datetime.fromisoformat(self.asOf.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("asOf must be an ISO-8601 timestamp") from exc
            if anchor.tzinfo is None:
                raise ValueError("asOf must include a timezone")
        return self


class ProjectionDependencyState(ProjectionContract):
    """Dependency state of a sibling projection this projection depends on."""

    projectionId: ProjectionId
    state: SectionState
    reason: Optional[str] = None


class ProjectionReadAuthorization(ProjectionContract):
    """Server-derived outer 360 decision authorizing one nested projection read.

    This is an internal runtime envelope, not caller-supplied request data. It
    binds the outer product slot's policy result to the exact tenant, subject,
    consumer provider, target projection, and declared read capability.
    """

    tenantId: str
    sourceSurfaceId: Experience360SurfaceId
    sourceSubject: ProjectionSubject
    sourceSlotId: str
    consumerProjectionId: ProjectionId
    targetProjectionId: ProjectionId
    capabilityKey: str
    policyState: Literal["allowed", "denied", "unknown", "redacted", "not_applicable"]
    policyIds: list[str] = Field(default_factory=list)
    policyEvaluatedAt: Optional[str] = None


class ProjectionContext(ProjectionContract):
    """Build-time context the runtime computes for a projection request."""

    projectionId: ProjectionId
    tenantId: str
    registryState: ProjectionRegistryState
    dependencyState: list[ProjectionDependencyState]
    asOf: Optional[str] = None
    warnings: list[str]
    experience360ReadAuthorizations: list[ProjectionReadAuthorization] = Field(
        default_factory=list,
        description="Server-derived outer 360 read decisions scoped to this provider call.",
    )


class ProjectionSection(ProjectionContract):
    """One rendered section of a projection result."""

    id: str
    state: SectionState
    title: Optional[str] = None
    content: Optional[Any] = None
    warnings: Optional[list[str]] = None
    canonicalAuthorityRefs: Optional[list[str]] = None


class ClaimEnvelope(ProjectionContract):
    """One claim a projection makes about its subject, backed by evidence refs.

    ``claimState`` carries the consolidated :class:`EpistemicStatus` for the
    claim so a derived/inferred claim can never render as a factual declaration.
    Optional: absent means the provider did not classify the claim, which a UI
    must treat as unclassified — never as factual. Message/transport facts are
    capped at ``observed``; a recipient-knowledge or author-intent claim is a
    structurally different object (the information/knowledge layer) and can
    never be granted a factual state by a delivery/engagement fact alone.
    """

    id: str
    kind: str
    subject: ProjectionSubject
    evidenceRefs: list[EvidenceRef]
    claims: list[str]
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    claimState: Optional[EpistemicStatus] = None
    # A claim is assigned to a product-frame slot only when the projection
    # provider names that stable slot explicitly. Claims without this mapping
    # remain projection-level evidence and are not copied into arbitrary slots.
    domainSlotIds: Optional[list[str]] = None


class ProjectionDegradation(ProjectionContract):
    """Engine-level (A8) degradation summary for a projection result.

    ``level`` is ``"none"`` (every section available), ``"partial"`` (some
    sections suppressed / degraded / missing) or ``"full"`` (the projection
    could not be satisfied). ``reasons`` are engine-computed and content-free
    with respect to provider diagnostics — provider exception messages are
    NEVER echoed here (they stay on the fail-isolated degraded result's
    ``degradedReasons``, which are exception class names only).
    """

    level: Literal["none", "partial", "full"]
    reasons: list[str]
    conflictedLenses: Optional[list[str]] = None
    missingDependencies: Optional[list[str]] = None


class ProjectionResult(ProjectionContract):
    """The result of running a projection over canonical Aether truth.

    ``digest`` / ``lensIds`` / ``temporalMode`` / ``degradation`` /
    ``suppressedSections`` are projection-engine (A8) extensions, strictly
    OPTIONAL so a provider that does not emit them (and any result produced by
    the P0 runtime before the engine landed) remains a valid result.
    """

    projectionId: ProjectionId
    tenantId: str
    contractVersion: str
    sections: list[ProjectionSection]
    claims: list[ClaimEnvelope]
    dependencyState: list[ProjectionDependencyState]
    asOf: Optional[str] = None
    generatedAt: str  # ISO-8601 UTC string (repo timestamp convention)
    page: Optional[PageInfo] = None
    degradedReasons: list[str]
    digest: Optional[str] = None
    lensIds: Optional[list[str]] = None
    temporalMode: Optional[str] = None
    degradation: Optional[ProjectionDegradation] = None
    suppressedSections: Optional[list[str]] = None


class Experience360ActorParty(ProjectionContract):
    """An actor reference with an explicit namespace and actor kind.

    This is a reference, not an identity assertion. ``kind`` and ``id`` retain
    the value asserted by the source or resolved by an authority according to
    the containing attribution field.
    """

    kind: ActorKind
    id: str
    namespace: Optional[str] = None
    displayName: Optional[str] = None

    @model_validator(mode="after")
    def actor_reference_is_explicit(self) -> "Experience360ActorParty":
        if not self.id.strip():
            raise ValueError("actor id must not be empty")
        if self.namespace is not None and not self.namespace.strip():
            raise ValueError("actor namespace must be omitted or non-empty")
        return self


class Experience360Delegation(ProjectionContract):
    """Evidence-backed, tenant-bounded delegation edge in an actor chain."""

    id: str
    tenantId: str
    delegator: Experience360ActorParty
    delegatee: Experience360ActorParty
    scope: list[str] = Field(min_length=1)
    validFrom: str
    validUntil: Optional[str] = None
    status: Literal["asserted", "granted", "verified", "revoked", "expired", "unknown"]
    evidenceRefs: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_delegation_window(self) -> "Experience360Delegation":
        """Reject malformed or reversed validity bounds when they are parseable."""

        from datetime import datetime

        if not self.id.strip() or not self.tenantId.strip():
            raise ValueError("delegation id and tenantId must not be empty")
        if any(not value.strip() for value in self.scope):
            raise ValueError("delegation scope entries must not be empty")

        def parse(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        try:
            start = parse(self.validFrom)
            end = parse(self.validUntil) if self.validUntil is not None else None
        except ValueError as exc:
            raise ValueError("delegation validity bounds must be ISO-8601 timestamps") from exc
        if end is not None:
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError("delegation validity bounds must include a timezone")
            if end <= start:
                raise ValueError("validUntil must be after validFrom")
        elif start.tzinfo is None:
            raise ValueError("delegation validity bounds must include a timezone")
        if len(self.scope) != len(set(self.scope)):
            raise ValueError("delegation scope must not contain duplicates")
        return self


class Experience360AuthorityDecision(ProjectionContract):
    """Authority result attributed to a named authority and its evidence."""

    tenantId: str
    outcome: Literal["allow", "deny", "pending", "unknown", "not_applicable"]
    authorityRef: Optional[str] = None
    decidedAt: Optional[str] = None
    policyRefs: list[str] = Field(default_factory=list)
    delegationRefs: list[str] = Field(default_factory=list)
    actionRefs: list[str] = Field(default_factory=list)
    resourceRefs: list[str] = Field(default_factory=list)
    executionRefs: list[str] = Field(default_factory=list)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    reasonCodes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def positive_or_negative_decision_requires_authority_and_evidence(
        self,
    ) -> "Experience360AuthorityDecision":
        if self.outcome in {"allow", "deny"} and (not self.authorityRef or not self.evidenceRefs):
            raise ValueError("allow/deny decisions require authorityRef and evidenceRefs")
        if not self.tenantId.strip():
            raise ValueError("authority decision tenantId must not be empty")
        if self.authorityRef is not None and not self.authorityRef.strip():
            raise ValueError("authorityRef must be omitted or non-empty")
        return self


class Experience360DriverScore(ProjectionContract):
    """Independent evidence support for each possible action driver.

    These values describe attribution evidence strength, not quality, risk, or
    mutually exclusive probabilities. A request can have both a human
    initiator and an agent executor, so the values are not normalized to sum
    to one.
    """

    humanDriven: float = Field(default=0.0, ge=0.0, le=1.0)
    agentDriven: float = Field(default=0.0, ge=0.0, le=1.0)
    systemDriven: float = Field(default=0.0, ge=0.0, le=1.0)
    unknown: float = Field(default=1.0, ge=0.0, le=1.0)


class Experience360ActorAttribution(ProjectionContract):
    """Keep source assertions, canonical resolution, execution, and authority distinct.

    An omitted actor or an ``unknown`` resolution is not a claim that the actor
    does not exist. Source assertions remain separate from canonical identity;
    an execution principal is not inferred from either one. A canonical
    execution-principal identity is populated only from a complete,
    tenant-scoped USER_ID resolution and does not grant action authority.
    """

    tenantId: str
    actorKind: Literal["human", "agent", "system", "unknown"] = "unknown"
    actorSubjectId: Optional[str] = None
    representedSubjectId: Optional[str] = None
    agentId: Optional[str] = None
    humanPrincipalId: Optional[str] = None
    authorityEdgeIds: list[str] = Field(default_factory=list)
    driverScore: Experience360DriverScore = Field(default_factory=Experience360DriverScore)
    confidence: Literal["low", "medium", "high", "verified"] = "low"
    explanation: str = "Actor or action-driver evidence is insufficient to resolve attribution."
    resolutionState: Literal["resolved", "ambiguous", "unresolved", "unknown", "not_applicable"] = (
        "unknown"
    )
    assertedSourceActor: Optional[Experience360ActorParty] = None
    resolvedCanonicalActor: Optional[Experience360ActorParty] = None
    executionPrincipal: Optional[Experience360ActorParty] = None
    executionPrincipalCanonicalIdentity: Optional[Experience360ActorParty] = None
    delegator: Optional[Experience360ActorParty] = None
    delegatee: Optional[Experience360ActorParty] = None
    delegationChain: list[Experience360Delegation] = Field(default_factory=list)
    authorityDecision: Optional[Experience360AuthorityDecision] = None
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonical_actor_requires_resolved_state(self) -> "Experience360ActorAttribution":
        if not self.tenantId.strip():
            raise ValueError("actor attribution tenantId must not be empty")
        for field_name in (
            "actorSubjectId",
            "representedSubjectId",
            "agentId",
            "humanPrincipalId",
        ):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must be omitted or non-empty")
        if len(self.authorityEdgeIds) != len(set(self.authorityEdgeIds)):
            raise ValueError("authorityEdgeIds must not contain duplicates")
        if any(not edge_id.strip() for edge_id in self.authorityEdgeIds):
            raise ValueError("authorityEdgeIds must contain only non-empty ids")
        if not self.explanation.strip():
            raise ValueError("actor attribution explanation must not be empty")
        if self.actorKind != "unknown" and not self.evidenceRefs:
            raise ValueError("resolved actorKind requires evidenceRefs")
        if self.actorKind == "agent" and (
            self.resolutionState != "resolved"
            or self.resolvedCanonicalActor is None
            or self.resolvedCanonicalActor.kind != "agent"
            or self.agentId != self.resolvedCanonicalActor.id
            or self.actorSubjectId != self.resolvedCanonicalActor.id
        ):
            raise ValueError("agent actor attribution requires one evidence-backed canonical Agent")
        if self.actorKind == "human" and not self.humanPrincipalId:
            raise ValueError("human actor attribution requires an authenticated human principal")
        if self.confidence == "verified" and not self.evidenceRefs:
            raise ValueError("verified attribution requires evidenceRefs")
        if self.resolvedCanonicalActor is not None and self.resolutionState != "resolved":
            raise ValueError("resolvedCanonicalActor requires resolutionState='resolved'")
        if self.resolutionState == "resolved" and self.resolvedCanonicalActor is None:
            raise ValueError("resolutionState='resolved' requires resolvedCanonicalActor")
        if self.resolvedCanonicalActor is not None and not self.evidenceRefs:
            raise ValueError("resolvedCanonicalActor requires evidenceRefs")
        if self.assertedSourceActor is not None and not self.evidenceRefs:
            raise ValueError("assertedSourceActor requires evidenceRefs")
        if self.executionPrincipal is not None and not self.evidenceRefs:
            raise ValueError("executionPrincipal requires evidenceRefs")
        if self.executionPrincipalCanonicalIdentity is not None and not self.evidenceRefs:
            raise ValueError("executionPrincipalCanonicalIdentity requires evidenceRefs")
        if self.executionPrincipalCanonicalIdentity is not None:
            if self.executionPrincipalCanonicalIdentity.kind != "human":
                raise ValueError("executionPrincipalCanonicalIdentity must name a Human entity")
            evidence_sources = {reference.source for reference in self.evidenceRefs}
            if not {
                "agent_executions",
                "identity_aliases",
                "identity_subjects",
            }.issubset(evidence_sources):
                raise ValueError(
                    "executionPrincipalCanonicalIdentity requires execution and USER_ID alias and subject evidence"
                )
        if (self.delegator is not None or self.delegatee is not None) and not (
            self.delegationChain or self.evidenceRefs
        ):
            raise ValueError("delegator/delegatee requires delegation evidence")
        if any(step.tenantId != self.tenantId for step in self.delegationChain):
            raise ValueError("delegationChain entries must match actor-attribution tenantId")
        delegation_ids = [step.id for step in self.delegationChain]
        if len(delegation_ids) != len(set(delegation_ids)):
            raise ValueError("delegationChain must not contain duplicate ids")

        def party_key(
            party: Experience360ActorParty,
        ) -> tuple[str, str, Optional[str]]:
            return (party.kind, party.id, party.namespace)

        for previous, following in zip(
            self.delegationChain, self.delegationChain[1:], strict=False
        ):
            if party_key(previous.delegatee) != party_key(following.delegator):
                raise ValueError("delegationChain must be continuous from delegator to delegatee")
        if self.delegationChain and self.delegator is not None:
            if party_key(self.delegator) != party_key(self.delegationChain[0].delegator):
                raise ValueError("delegator must match the first delegationChain party")
        if self.delegationChain and self.delegatee is not None:
            if party_key(self.delegatee) != party_key(self.delegationChain[-1].delegatee):
                raise ValueError("delegatee must match the last delegationChain party")
        if self.authorityDecision is not None and self.authorityDecision.tenantId != self.tenantId:
            raise ValueError("authorityDecision must match actor-attribution tenantId")
        return self


class Experience360Freshness(ProjectionContract):
    """Freshness assessment with absent measurements kept explicitly unknown."""

    state: Literal["fresh", "stale", "missing", "unknown", "unavailable", "not_applicable"] = (
        "unknown"
    )
    sourceAsOf: Optional[str] = None
    evaluatedAt: Optional[str] = None
    ageSeconds: Optional[float] = Field(default=None, ge=0)
    maxAgeSeconds: Optional[float] = Field(default=None, ge=0)


class Experience360Quality(ProjectionContract):
    """Quality assessment; no score is fabricated when evidence is absent."""

    state: Literal[
        "adequate", "partial", "insufficient", "conflicted", "unknown", "not_applicable"
    ] = "unknown"
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    reasonCodes: list[str] = Field(default_factory=list)


class Experience360PolicyDisposition(ProjectionContract):
    """Policy result and redaction metadata for a frame or slot.

    On a slot, JSON Pointers are relative to that slot's ``content`` object.
    Frame-level dispositions summarize policy state; redaction paths belong on
    the affected slots so their target content is unambiguous.
    """

    state: Literal["allowed", "redacted", "denied", "unknown", "not_applicable"] = "unknown"
    policyIds: list[str] = Field(default_factory=list)
    redactedFieldPaths: list[str] = Field(
        default_factory=list,
        description=(
            "On a slot, RFC 6901 JSON Pointers relative to that slot's content "
            "object for fields denied by policy; never include redacted values. "
            "Until providers support field-scoped reads and claim dependencies, "
            "any redacted slot is suppressed before it is read."
        ),
    )
    reasonCodes: list[str] = Field(default_factory=list)
    evaluatedAt: Optional[str] = None
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)


class Experience360PolicyEvaluation(ProjectionContract):
    """Tenant- and surface-bound policy result consumed before projection reads."""

    surfaceId: Experience360SurfaceId
    tenantId: str
    evaluatedAt: str
    frameDisposition: Experience360PolicyDisposition
    slotDispositions: dict[str, Experience360PolicyDisposition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def frame_scope_and_redaction_are_explicit(
        self,
    ) -> "Experience360PolicyEvaluation":
        if not self.tenantId.strip():
            raise ValueError("tenantId must not be empty")
        if self.frameDisposition.redactedFieldPaths:
            raise ValueError("frame policy cannot use slot-relative redaction paths")
        for disposition in self.slotDispositions.values():
            if disposition.evaluatedAt is not None and disposition.evaluatedAt != self.evaluatedAt:
                raise ValueError("slot policy timestamps must match evaluation timestamp")
        return self


class Experience360ProjectionProvenance(ProjectionContract):
    """Lineage from a frame slot to a projection section, claim, or authority read."""

    tenantId: str
    projectionId: Optional[ProjectionId] = None
    sourceState: SectionState
    generatedAt: str
    sourceKind: Literal["section", "claim", "authority"] = "section"
    sectionId: Optional[str] = None
    claimId: Optional[str] = None
    asOf: Optional[str] = None
    digest: Optional[str] = None
    claimOrigin: Literal[
        "canonical_authority",
        "source_assertion",
        "derived",
        "inference",
        "unknown",
    ] = "unknown"
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    claimStates: list[EpistemicStatus] = Field(default_factory=list)
    canonicalAuthorityRefs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def asserted_origin_requires_evidence(self) -> "Experience360ProjectionProvenance":
        if self.sourceKind == "section" and (
            self.projectionId is None or not self.sectionId or self.claimId is not None
        ):
            raise ValueError("section provenance requires projectionId and only sectionId")
        if self.sourceKind == "claim" and (
            self.projectionId is None or not self.claimId or self.sectionId is not None
        ):
            raise ValueError("claim provenance requires projectionId and only claimId")
        if self.sourceKind == "authority" and (
            self.projectionId is not None
            or self.claimId is not None
            or self.sectionId is not None
            or not self.canonicalAuthorityRefs
        ):
            raise ValueError("authority provenance requires canonicalAuthorityRefs only")
        if self.claimOrigin != "unknown" and not self.evidenceRefs:
            raise ValueError("non-unknown claimOrigin requires evidenceRefs")
        return self


class Experience360FrameRequest(ProjectionContract):
    """Tenant-scoped request to compose any registered product 360 surface."""

    surfaceId: Experience360SurfaceId
    tenantId: str
    subject: ProjectionSubject
    requestedSlotIds: Optional[list[str]] = None
    asOf: Optional[str] = None
    timeRange: Optional[TimeRangeFilter] = None
    includeEvidence: bool = True
    lensIds: Optional[list[str]] = None
    page: Optional[PageRequest] = None
    requestedBy: Optional[Experience360ActorParty] = None
    purpose: Optional[str] = None
    authorizationContextRef: Optional[str] = None

    @model_validator(mode="after")
    def validate_frame_request(self) -> "Experience360FrameRequest":
        if not self.tenantId.strip():
            raise ValueError("tenantId must not be empty")
        if not self.subject.id.strip():
            raise ValueError("subject.id must not be empty")
        if self.requestedSlotIds is not None:
            if not self.requestedSlotIds:
                raise ValueError("requestedSlotIds must be omitted or non-empty")
            if len(self.requestedSlotIds) != len(set(self.requestedSlotIds)):
                raise ValueError("requestedSlotIds must not contain duplicates")
        if self.asOf is not None:
            from datetime import datetime

            try:
                anchor = datetime.fromisoformat(self.asOf.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("asOf must be an ISO-8601 timestamp") from exc
            if anchor.tzinfo is None:
                raise ValueError("asOf must include a timezone")
        return self


class Experience360FrameSlot(ProjectionContract):
    """A catalog-defined domain slot, including state, policy, and lineage."""

    id: str
    requirement: Literal["required", "optional"]
    state: Experience360SlotState
    description: Optional[str] = None
    canonicalAuthorityRefs: list[str] = Field(default_factory=list)
    content: Optional[Any] = None
    claims: list[ClaimEnvelope] = Field(default_factory=list)
    provenance: list[Experience360ProjectionProvenance] = Field(default_factory=list)
    evidenceRefs: list[EvidenceRef] = Field(default_factory=list)
    freshness: Optional[Experience360Freshness] = None
    quality: Optional[Experience360Quality] = None
    policyDisposition: Experience360PolicyDisposition = Field(
        default_factory=Experience360PolicyDisposition
    )
    actorAttribution: Optional[Experience360ActorAttribution] = None
    limitations: list[str] = Field(default_factory=list)
    reasonCodes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_content_for_unavailable_state(self) -> "Experience360FrameSlot":
        if (
            self.state in {"missing", "unknown", "suppressed", "unavailable"}
            and self.content is not None
        ):
            raise ValueError(f"slot state '{self.state}' cannot carry content")
        if self.policyDisposition.state in {"denied", "unknown"} and self.content is not None:
            raise ValueError("denied or unevaluated slot policy cannot carry content")
        if (
            self.policyDisposition.state == "redacted"
            and self.content is not None
            and not self.policyDisposition.redactedFieldPaths
        ):
            raise ValueError("redacted slot content requires explicit redaction paths")
        if self.state in {"available", "degraded"} and self.content is not None:
            has_evidence = bool(self.evidenceRefs) or any(
                item.evidenceRefs for item in self.provenance
            )
            if not self.provenance or not has_evidence:
                raise ValueError(
                    f"{self.state} slot content requires projection provenance and evidenceRefs"
                )
            if any(not claim.evidenceRefs for claim in self.claims):
                raise ValueError("claims in a content-bearing slot require evidenceRefs")
        elif self.state == "available":
            if self.content is None:
                raise ValueError("available slot state requires content")
            has_evidence = bool(self.evidenceRefs) or any(
                item.evidenceRefs for item in self.provenance
            )
            if not self.provenance or not has_evidence:
                raise ValueError(
                    "available slot content requires projection provenance and evidenceRefs"
                )
            if any(not claim.evidenceRefs for claim in self.claims):
                raise ValueError("claims in an available slot require evidenceRefs")
        elif self.claims:
            raise ValueError("claims can only be included in available or evidenced degraded slots")
        return self


class Experience360Frame(ProjectionContract):
    """Unified backend response for all 18 product 360 surfaces.

    This is a governed read/projection envelope. It does not claim ownership of
    canonical truth; each slot keeps its provider lineage and epistemic state.
    """

    surfaceId: Experience360SurfaceId
    tenantId: str
    subject: ProjectionSubject
    surfaceCatalogVersion: str
    contractVersion: str
    generatedAt: str
    asOf: Optional[str] = None
    state: Experience360FrameState
    slots: list[Experience360FrameSlot]
    freshness: Experience360Freshness = Field(default_factory=Experience360Freshness)
    quality: Experience360Quality = Field(default_factory=Experience360Quality)
    policyDisposition: Experience360PolicyDisposition = Field(
        default_factory=Experience360PolicyDisposition
    )
    actorAttribution: Optional[Experience360ActorAttribution] = None
    degradation: Optional[ProjectionDegradation] = None
    warnings: list[str] = Field(default_factory=list)
    ownsCanonicalTruth: Literal[False] = False

    @model_validator(mode="after")
    def enforce_tenant_scope(self) -> "Experience360Frame":
        slot_ids = [slot.id for slot in self.slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("frame slots must not contain duplicate ids")
        surface_definition = getattr(
            _generated_registry, "PRODUCT_360_SURFACE_DEFINITIONS", {}
        ).get(self.surfaceId)
        if isinstance(surface_definition, dict):
            expected_requirements = {
                item["id"]: item.get("requirement", "required")
                for item in surface_definition.get("domainSlots", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for slot in self.slots:
                if slot.id not in expected_requirements:
                    raise ValueError("frame contains a slot outside the product catalog")
                if slot.requirement != expected_requirements[slot.id]:
                    raise ValueError("frame slot requirement differs from the product catalog")
        if self.actorAttribution is not None and self.actorAttribution.tenantId != self.tenantId:
            raise ValueError("actorAttribution must match frame tenantId")
        for slot in self.slots:
            if (
                slot.actorAttribution is not None
                and slot.actorAttribution.tenantId != self.tenantId
            ):
                raise ValueError("slot actorAttribution must match frame tenantId")
            if any(item.tenantId != self.tenantId for item in slot.provenance):
                raise ValueError("slot provenance must match frame tenantId")
        return self


__all__ = [
    "ClaimEnvelope",
    "EXPERIENCE_360_FRAME_STATES",
    "Experience360ActorAttribution",
    "Experience360ActorParty",
    "Experience360AuthorityDecision",
    "Experience360Delegation",
    "Experience360DriverScore",
    "Experience360Frame",
    "Experience360FrameRequest",
    "Experience360FrameSlot",
    "Experience360FrameState",
    "Experience360Freshness",
    "Experience360PolicyDisposition",
    "Experience360PolicyEvaluation",
    "Experience360ProjectionProvenance",
    "Experience360Quality",
    "Experience360SlotState",
    "Experience360SurfaceId",
    "PRODUCT_360_SURFACE_IDS",
    "ProjectionContext",
    "ProjectionDegradation",
    "ProjectionDependencyState",
    "ProjectionReadAuthorization",
    "ProjectionId",
    "ProjectionRegistryState",
    "ProjectionRequest",
    "ProjectionResult",
    "ProjectionSection",
    "ProjectionSubject",
    "ProjectionSubjectKind",
    "SectionState",
]
