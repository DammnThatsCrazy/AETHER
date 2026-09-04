"""Infrastructure360 — read-only intelligence projection over canonical truth.

This module is the **runtime provider** for the infrastructure360 projection
(the 19th projection on the Intelligence Projection Plane). It implements the
:class:`IntelligenceProjectionProvider
<shared.intelligence_projections.provider.IntelligenceProjectionProvider>`
``typing.Protocol`` (``projection_id`` / ``contract_version`` / ``async
project``) — there is no ``Base360`` superclass to inherit from.

Doctrine (ADR-010): a 360 is an intelligence projection over canonical Aether
truth, never a competing system of record. This provider therefore:

* **never writes** — ``graph_mutation_policy == "read_only"`` and there is no
  write path (no graph write, no mutation call, nothing). The projection reads
  canonical infrastructure authorities and projects.
* **reads defensively** — canonical sources
  (``services/provider_runtime/registry.py`` provider/service health,
  ``services/model_runtime/`` model-service health, ``services/noesis/``
  deployment records) are imported lazily; an authority that cannot be read
  degrades its sections to a typed ``degraded`` / ``missing`` / ``empty``
  state — the provider never crashes and never fabricates.
* **is tenant-scoped end to end** — every record is derived from
  ``request.tenantId``; the provider filters any reader output by tenant as a
  server-authoritative backstop, so tenant A's projection can never surface
  tenant B's deployments or evidence.
* **grounds every claim in ``EvidenceRef``** — a claim that cannot be grounded
  is a typed section state, never a silent assertion.
* **raises only ``ProjectionError`` subclasses** — in practice the provider
  degrades rather than raises, and any unexpected exception is fail-isolated by
  the runtime registry.

The ``canonical_reader`` constructor seam lets callers (and tests) supply a
deterministic tenant-scoped reader; the default reader
(:func:`_read_canonical_infrastructure`) performs the lazy defensive reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import ValidationError
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
from services.infrastructure.contracts import (
    Deployment,
    InfrastructureEntity,
    InfrastructureState,
)
from services.infrastructure.taxonomy import INFRASTRUCTURE_FACT_CATEGORIES
from services.operational_intelligence.models import EvidenceRef

__all__ = [
    "CanonicalInfrastructureRead",
    "DEFAULT_SECTION_IDS",
    "Infrastructure360Provider",
    "build_projection_request",
    "register_provider",
]

# The projection's registry-declared capability keys (surface join). The route
# layer gates on ``infrastructure360.read``; ``explore`` is the read-only
# exploration counterpart.
READ_CAPABILITY = "infrastructure360.read"
EXPLORE_CAPABILITY = "infrastructure360.explore"

# Output sections, exactly the registry row's ``outputSections``.
DEFAULT_SECTION_IDS: tuple[str, ...] = (
    "summary",
    "state",
    "deployments",
    "evidence",
    "findings",
)


@dataclass(frozen=True)
class CanonicalInfrastructureRead:
    """A tenant-scoped snapshot of canonical infrastructure truth.

    Produced by a ``canonical_reader`` (a ``Callable[[str],
    CanonicalInfrastructureRead]``) and consumed by the provider. ``entities`` /
    ``deployments`` MUST be tenant-keyed records; the provider re-filters them
    by ``tenant_id`` as a server-authoritative backstop.

    ``degraded_sources`` names the canonical authorities
    (:data:`INFRASTRUCTURE_FACT_CATEGORIES
    <services.infrastructure.taxonomy.INFRASTRUCTURE_FACT_CATEGORIES>`) that
    could not be read. Sections built from a degraded source are typed
    ``degraded`` / ``missing`` — the provider never fabricates content for them.
    """

    entities: tuple[InfrastructureEntity, ...] = ()
    deployments: tuple[Deployment, ...] = ()
    health: dict[str, str] = field(default_factory=dict)
    degraded_sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class Infrastructure360Provider:
    """Read-only infrastructure360 projection provider (Protocol-conformant)."""

    projection_id: str = "infrastructure360"
    contract_version: str = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy: str = "read_only"

    def __init__(
        self,
        canonical_reader: Optional[Callable[[str], CanonicalInfrastructureRead]] = None,
    ) -> None:
        self._canonical_reader = canonical_reader or _read_canonical_infrastructure

    # ── IntelligenceProjectionProvider protocol ─────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run the infrastructure360 projection over canonical truth.

        Everything derives from ``request.tenantId``; the provider filters the
        reader's output by tenant so no cross-tenant record can leak. Sections
        ``summary/state/deployments/evidence/findings`` are always present, each
        in a valid ``SectionState``; every claim carries ``EvidenceRef``.
        """
        tenant_id = request.tenantId
        read = self._canonical_reader(tenant_id)

        # Server-authoritative tenant scope: even a misbehaving reader cannot
        # surface another tenant's records.
        entities = tuple(e for e in read.entities if e.tenant_id == tenant_id)
        deployments = tuple(d for d in read.deployments if d.tenant_id == tenant_id)
        evidence_refs = _collect_evidence(entities, deployments)

        # Honesty backstop: only canonical authority categories may degrade a
        # section — a bogus degraded-source key claims no authority.
        read = _with_known_degraded_sources(read)

        sections = self._build_sections(
            request=request,
            tenant_id=tenant_id,
            read=read,
            entities=entities,
            deployments=deployments,
            evidence_refs=evidence_refs,
        )
        claims = self._build_claims(
            request=request,
            tenant_id=tenant_id,
            entities=entities,
            deployments=deployments,
            evidence_refs=evidence_refs,
        )

        return _build_projection_result(
            projection_id=self.projection_id,
            tenant_id=tenant_id,
            sections=sections,
            claims=claims,
            dependency_state=list(context.dependencyState),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── Section / claim assembly (pure, deterministic) ──────────────────────

    def _build_sections(
        self,
        *,
        request: ProjectionRequest,
        tenant_id: str,
        read: CanonicalInfrastructureRead,
        entities: tuple[InfrastructureEntity, ...],
        deployments: tuple[Deployment, ...],
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> list[ProjectionSection]:
        degraded = set(read.degraded_sources)
        warnings = list(read.warnings) or None
        sections: list[ProjectionSection] = []

        # summary — available when there is any tenant content; otherwise the
        # honest typed state (degraded when an authority is unreadable, else
        # empty).
        if entities or deployments:
            sections.append(
                ProjectionSection(
                    id="summary",
                    state="available",
                    title="Infrastructure Summary",
                    content={
                        "tenantId": tenant_id,
                        "entityCount": len(entities),
                        "deploymentCount": len(deployments),
                        "degradedSources": sorted(degraded),
                    },
                    warnings=warnings,
                )
            )
        else:
            sections.append(
                ProjectionSection(
                    id="summary",
                    state="degraded" if degraded else "empty",
                    title="Infrastructure Summary",
                    content={
                        "tenantId": tenant_id,
                        "degradedSources": sorted(degraded),
                    },
                    warnings=warnings,
                )
            )

        # state — distribution by InfrastructureState.
        if entities:
            by_state: dict[str, int] = {}
            for entity in entities:
                by_state[entity.state.value] = by_state.get(entity.state.value, 0) + 1
            sections.append(
                ProjectionSection(
                    id="state",
                    state="available",
                    title="Infrastructure State",
                    content={"tenantId": tenant_id, "byState": by_state},
                )
            )
        elif degraded & {"infrastructure_facts", "infrastructure_state"}:
            sections.append(
                ProjectionSection(
                    id="state",
                    state="degraded",
                    title="Infrastructure State",
                    content={"tenantId": tenant_id},
                )
            )
        else:
            sections.append(
                ProjectionSection(
                    id="state", state="empty", title="Infrastructure State"
                )
            )

        # deployments — real deployment records keyed by tenant when present.
        if deployments:
            sections.append(
                ProjectionSection(
                    id="deployments",
                    state="available",
                    title="Deployments",
                    content={
                        "tenantId": tenant_id,
                        "deployments": [
                            deployment.model_dump(mode="json") for deployment in deployments
                        ],
                    },
                )
            )
        elif "deployments" in degraded:
            sections.append(
                ProjectionSection(
                    id="deployments",
                    state="degraded",
                    title="Deployments",
                    content={"tenantId": tenant_id},
                    warnings=warnings,
                )
            )
        else:
            sections.append(
                ProjectionSection(
                    id="deployments", state="empty", title="Deployments"
                )
            )

        # evidence — the EvidenceRefs grounding this tenant's claims.
        if evidence_refs:
            sections.append(
                ProjectionSection(
                    id="evidence",
                    state="available",
                    title="Evidence",
                    content={
                        "evidence": [ref.model_dump(mode="json") for ref in evidence_refs]
                    },
                )
            )
        elif degraded:
            sections.append(
                ProjectionSection(
                    id="evidence",
                    state="degraded",
                    title="Evidence",
                    content={"tenantId": tenant_id},
                )
            )
        else:
            sections.append(
                ProjectionSection(id="evidence", state="empty", title="Evidence")
            )

        # findings — derived observations, each grounded in evidence.
        findings = _derive_findings(tenant_id, entities, deployments)
        if findings:
            sections.append(
                ProjectionSection(
                    id="findings",
                    state="available",
                    title="Findings",
                    content={"tenantId": tenant_id, "findings": findings},
                )
            )
        elif degraded:
            sections.append(
                ProjectionSection(
                    id="findings",
                    state="degraded",
                    title="Findings",
                    content={"tenantId": tenant_id},
                )
            )
        else:
            sections.append(
                ProjectionSection(
                    id="findings", state="empty", title="Findings"
                )
            )

        return sections

    def _build_claims(
        self,
        *,
        request: ProjectionRequest,
        tenant_id: str,
        entities: tuple[InfrastructureEntity, ...],
        deployments: tuple[Deployment, ...],
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []

        if not (entities or deployments) or not evidence_refs:
            return claims

        claims.append(
            ClaimEnvelope(
                id=f"summary.{tenant_id}",
                kind="summary",
                subject=request.subject,
                evidenceRefs=list(evidence_refs),
                claims=[
                    f"Tenant {tenant_id} operates {len(entities)} infrastructure "
                    f"entities and {len(deployments)} deployments."
                ],
                confidence=1.0,
            )
        )

        # One finding claim per derived finding, grounded in its own evidence.
        for finding in _derive_findings(tenant_id, entities, deployments):
            claims.append(
                ClaimEnvelope(
                    id=f"finding.{tenant_id}.{finding['key']}",
                    kind="finding",
                    subject=request.subject,
                    evidenceRefs=finding["evidenceRefs"],
                    claims=[finding["finding"]],
                    confidence=finding["confidence"],
                )
            )
        return claims


# ── Projection-plane wire-contract seam (order-resilient) ─────────────────────
# The shared contracts type ``ProjectionId`` as a Literal derived from the
# generated registry. The infrastructure360 row lands in a SEPARATE integration
# step (the 19th row + regeneration), so until that row exists the Literal does
# not yet accept "infrastructure360" and a strict construction would fail. These
# helpers therefore build STRICT first and fall back to ``model_construct`` ONLY
# when the sole failure is the not-yet-registered projectionId Literal. Once the
# orchestrator regenerates the registry, the strict path is taken and full
# validation (including the projection plane's ``extra="forbid"``) applies.
# ``model_construct`` never swallows any other validation failure.

def _only_projection_id_literal_errors(exc: ValidationError) -> bool:
    """True when every error is the projectionId Literal rejection only."""
    errors = exc.errors()
    if not errors:
        return False
    for err in errors:
        if err.get("type") != "literal_error" or err.get("loc") != ("projectionId",):
            return False
    return True


def build_projection_request(
    *,
    projection_id: str,
    tenant_id: str,
    subject: ProjectionSubject,
) -> ProjectionRequest:
    """Build a strict :class:`ProjectionRequest`, tolerating a not-yet-registered id."""
    try:
        return ProjectionRequest(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )
    except ValidationError as exc:
        if not _only_projection_id_literal_errors(exc):
            raise
        return ProjectionRequest.model_construct(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )


def _build_projection_result(
    *,
    projection_id: str,
    tenant_id: str,
    sections: list[ProjectionSection],
    claims: list[ClaimEnvelope],
    dependency_state: list[Any],
    generated_at: str,
) -> ProjectionResult:
    """Build a strict :class:`ProjectionResult`, tolerating a not-yet-registered id."""
    try:
        return ProjectionResult(
            projectionId=projection_id,
            tenantId=tenant_id,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=claims,
            dependencyState=dependency_state,
            generatedAt=generated_at,
            degradedReasons=[],
        )
    except ValidationError as exc:
        if not _only_projection_id_literal_errors(exc):
            raise
        return ProjectionResult.model_construct(
            projectionId=projection_id,
            tenantId=tenant_id,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=claims,
            dependencyState=dependency_state,
            generatedAt=generated_at,
            degradedReasons=[],
        )


# ── Evidence / findings derivation (pure) ─────────────────────────────────────

def _collect_evidence(
    entities: tuple[InfrastructureEntity, ...],
    deployments: tuple[Deployment, ...],
) -> tuple[EvidenceRef, ...]:
    """EvidenceRefs for the records the projection composes over.

    Entity records ground as ``type="entity"`` facts from the
    ``infrastructure_facts`` authority; deployment records ground as
    ``type="event"`` facts from the ``deployments`` authority.
    """
    refs: list[EvidenceRef] = []
    for entity in entities:
        refs.append(
            EvidenceRef(
                id=f"fact:{entity.id}",
                type="entity",
                source="infrastructure_facts",
            )
        )
    for deployment in deployments:
        refs.append(
            EvidenceRef(
                id=f"dep:{deployment.id}",
                type="event",
                source="deployments",
                observedAt=deployment.started_at,
            )
        )
    return tuple(refs)


def _entity_evidence(
    entities: tuple[InfrastructureEntity, ...],
    state: InfrastructureState,
) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(id=f"fact:{entity.id}", type="entity", source="infrastructure_facts")
        for entity in entities
        if entity.state is state
    )


def _deployment_evidence(
    deployments: tuple[Deployment, ...],
    state: InfrastructureState,
) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            id=f"dep:{deployment.id}",
            type="event",
            source="deployments",
            observedAt=deployment.started_at,
        )
        for deployment in deployments
        if deployment.state is state
    )


def _derive_findings(
    tenant_id: str,
    entities: tuple[InfrastructureEntity, ...],
    deployments: tuple[Deployment, ...],
) -> list[dict[str, Any]]:
    """Deterministic, evidence-grounded findings (empty when nothing notable).

    Each finding is ``{"key", "finding", "evidenceRefs", "confidence"}``. A
    finding is only emitted when it is grounded — no evidence, no finding.
    """
    findings: list[dict[str, Any]] = []

    failed_entities = _entity_evidence(entities, InfrastructureState.FAILED)
    if failed_entities:
        findings.append(
            {
                "key": "failed_entities",
                "finding": (
                    f"Tenant {tenant_id} has {len(failed_entities)} infrastructure "
                    "entities in FAILED state."
                ),
                "evidenceRefs": list(failed_entities),
                "confidence": 1.0,
            }
        )

    degraded_entities = _entity_evidence(entities, InfrastructureState.DEGRADED)
    if degraded_entities:
        findings.append(
            {
                "key": "degraded_entities",
                "finding": (
                    f"Tenant {tenant_id} has {len(degraded_entities)} infrastructure "
                    "entities in DEGRADED state."
                ),
                "evidenceRefs": list(degraded_entities),
                "confidence": 0.9,
            }
        )

    failed_deployments = _deployment_evidence(deployments, InfrastructureState.FAILED)
    if failed_deployments:
        findings.append(
            {
                "key": "failed_deployments",
                "finding": (
                    f"Tenant {tenant_id} has {len(failed_deployments)} FAILED "
                    "deployments."
                ),
                "evidenceRefs": list(failed_deployments),
                "confidence": 1.0,
            }
        )

    active_deployments = _deployment_evidence(deployments, InfrastructureState.ACTIVE)
    if active_deployments and not (failed_entities or degraded_entities):
        findings.append(
            {
                "key": "healthy",
                "finding": (
                    f"Tenant {tenant_id} has {len(active_deployments)} ACTIVE "
                    "deployments and no failed or degraded entities."
                ),
                "evidenceRefs": list(active_deployments),
                "confidence": 0.9,
            }
        )

    return findings


def _with_known_degraded_sources(read: CanonicalInfrastructureRead) -> CanonicalInfrastructureRead:
    """Return ``read`` with ``degraded_sources`` filtered to known authorities.

    Keeps the degraded-source vocabulary honest: only the canonical fact
    categories (``infrastructure_facts`` / ``infrastructure_state`` /
    ``deployments``) may type a section degraded.
    """
    known = frozenset(INFRASTRUCTURE_FACT_CATEGORIES)
    filtered = tuple(source for source in read.degraded_sources if source in known)
    if filtered == read.degraded_sources:
        return read
    return CanonicalInfrastructureRead(
        entities=read.entities,
        deployments=read.deployments,
        health=read.health,
        degraded_sources=filtered,
        warnings=read.warnings,
    )


# ── Default defensive canonical-source reader ────────────────────────────────

def _read_canonical_infrastructure(tenant_id: str) -> CanonicalInfrastructureRead:
    """Default lazy, defensive read of canonical infrastructure authorities.

    * ``infrastructure_facts`` / ``infrastructure_state`` ← provider-runtime
      registry health and model-runtime presence.
    * ``deployments`` ← a mounted deployments authority (today: none is mounted,
      so the source is structurally absent and degrades honestly).

    Every import is lazy and guarded; an unreadable authority is named in
    ``degraded_sources`` (never raised, never fabricated).
    """
    entities: list[InfrastructureEntity] = []
    deployments: list[Deployment] = []
    health: dict[str, str] = {}
    degraded: list[str] = []
    warnings: list[str] = []

    # infrastructure_facts / infrastructure_state ← provider-runtime health.
    try:
        from services.provider_runtime.registry import provider_registry

        for identity_key in provider_registry.sources():
            health[identity_key] = "active"
        if not health:
            warnings.append(
                "infrastructure_state: no provider-runtime providers installed"
            )
    except Exception as exc:  # noqa: BLE001 - defensive canonical read
        degraded.append("infrastructure_facts")
        degraded.append("infrastructure_state")
        warnings.append(
            f"infrastructure_state: provider-runtime unreadable ({type(exc).__name__})"
        )

    # infrastructure_state ← model-runtime presence.
    try:
        import services.model_runtime.service as _model_runtime_service  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - defensive canonical read
        degraded.append("infrastructure_state")
        warnings.append(
            f"infrastructure_state: model-runtime unreadable ({type(exc).__name__})"
        )

    # deployments ← services/noesis deployment records, where mounted.
    try:
        import services.noesis as _noesis  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - defensive canonical read
        degraded.append("deployments")
        warnings.append(f"deployments: noesis unreadable ({type(exc).__name__})")

    return CanonicalInfrastructureRead(
        entities=tuple(entities),
        deployments=tuple(deployments),
        health=health,
        degraded_sources=tuple(dict.fromkeys(degraded)),
        warnings=tuple(warnings),
    )


# ── Registration seam ─────────────────────────────────────────────────────────

def register_provider(registry: Any) -> None:
    """Register the infrastructure360 provider on a ``ProviderRegistry``.

    ``registry`` is any object implementing ``register(provider, *, source=...)``
    (the plane's :class:`ProviderRegistry
    <shared.intelligence_projections.registry.ProviderRegistry>` or a test
    double). The provider is registered under ``source="services/infrastructure"``
    so the plane can trace where a projection came from. This function does NOT
    auto-register on the global ``projection_registry`` at import time — the
    plane's registry is wired by the caller (the service wiring / app mount),
    keeping this module importable without side effects.
    """
    registry.register(Infrastructure360Provider(), source="services/infrastructure")
