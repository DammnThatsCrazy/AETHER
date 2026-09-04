"""Outcome360 intelligence-projection provider.

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record (ADR-010). :class:`Outcome360Provider` is the
``measurement_360`` provider for the ``outcome360`` registry row: it projects
canonical outcome truth (``outcome_facts`` / ``measurement_contract``) into the
five registered output sections (``summary``, ``state``, ``evidence``,
``outcomes``, ``findings``) with every claim grounded in a reused
:class:`EvidenceRef`.

Invariants:

* **Tenant-scoped end to end** — every outcome row the provider touches carries
  ``request.tenantId``; there is no shared mutable state across tenants.
* **Pure read** — ``graphMutationPolicy`` is ``read_only``; the provider has no
  write path and never mutates canonical state.
* **Fail-isolated** — a missing backing source (no injected store, the
  measurement engine unavailable at runtime, the ``temporal360`` dependency not
  yet implemented) DEGRADES the affected section to a typed state
  (``missing``/``empty``) and records it in ``dependencyState`` — the
  projection never raises and never returns an incomplete plane result.
* **No redefinition** — canonical primitives (:class:`EvidenceRef`, page and
  time-range) come from ``services/operational_intelligence/models.py``; the
  outcome package declares no second copies.
"""

from __future__ import annotations

import typing
from datetime import datetime, timezone
from typing import Any, Optional

from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionDependencyState,
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
from services.operational_intelligence.models import (
    EvidenceRef,
    PageInfo,
)

from services.measurement.outcome.contracts import Outcome, OutcomeState
from services.measurement.outcome.registry import outcome_type_registry

# The metric ref the outcome360 registry row declares.
_JOURNEY_COMPLETION_DEFINITION_REF = "journey_completion"

# Registry outputSections for outcome360 (mirrors the registry row; kept local
# only as the provider's own render plan — the registry owns the canonical list).
_OUTCOME360_SECTIONS = ("summary", "state", "evidence", "outcomes", "findings")

_SECTION_TITLES = {
    "summary": "Outcome summary",
    "state": "Outcome state distribution",
    "evidence": "Outcome evidence",
    "outcomes": "Outcome rows",
    "findings": "Outcome findings",
}


class OutcomeStore(typing.Protocol):
    """A tenant-scoped reader over canonical outcome truth.

    The provider depends only on this narrow read surface — repositories,
    measurement Gold/Silver and in-memory test stores all satisfy it. Returning
    outcomes for any tenant other than the requested one is a tenant-isolation
    violation the provider never performs itself.
    """

    async def list_outcomes(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[Outcome]:
        """Outcome rows for ``subject`` scoped to ``tenant_id``."""
        ...


def _measurement_outcome_store() -> Optional[OutcomeStore]:
    """Best-effort canonical backing over the measurement engine.

    Kept import-defensive and self-contained: the measurement engine is an
    integration point that may be unavailable in a minimal runtime (missing
    dependencies, no credentials). When this returns ``None`` the provider
    degrades its outcome-bearing sections to typed ``missing`` — it never
    crashes the plane (ADR-010 fail-isolation).

    The repository-backed adapter for canonical outcome rows lands with the
    outcome repository (S6); the wiring point is asserted here so the provider
    is never a competing system of record — it reads measurement canonical
    truth when one exists.
    """
    try:
        from services.measurement.engine.journey_compiler import (  # noqa: F401
            JourneyCompiler,
        )
        from services.measurement.engine.gold_materializer import (  # noqa: F401
            materialize_journey_economics,
        )
        from services.measurement.contracts import (  # noqa: F401
            CanonicalConversion,
            JourneyVersion,
        )
    except Exception:  # noqa: BLE001 - defensive: never crash the plane
        return None
    return None  # outcome repository adapter lands with the vertical slice


class Outcome360Provider:
    """The ``outcome360`` intelligence projection provider (read_only)."""

    projection_id = "outcome360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, outcome_store: Optional[OutcomeStore] = None) -> None:
        """``outcome_store`` may be injected (tests / repositories). Defaults to
        a best-effort canonical backing that degrades to ``missing`` when
        unavailable."""
        self._outcome_store: Optional[OutcomeStore] = outcome_store

    # ── IntelligenceProjectionProvider ───────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one tenant-scoped outcome360 projection over canonical truth."""
        outcomes = await self._load_outcomes(request)

        # The registry declares outcome360 depends on temporal360. A missing /
        # degraded dependency is a computed state, NEVER a raise: temporal
        # comparison degrades to a window projection and the dependency stays
        # visible in the result's dependencyState.
        temporal = _dependency_state(context, "temporal360")
        temporal_mode = _effective_temporal_mode(request.temporalMode, temporal)
        warnings: list[str] = []
        if temporal is not None and temporal.state != "available":
            warnings.append(
                f"dependency temporal360 is {temporal.state}; "
                f"temporal mode {request.temporalMode!r} degrades to "
                f"{temporal_mode!r}"
            )

        render_outcomes, page = self._page_slice(request, outcomes)
        sections = self._build_sections(
            request, render_outcomes, temporal_mode, temporal, warnings
        )
        claims = self._build_claims(request, render_outcomes)

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            asOf=context.asOf,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            page=page,
            degradedReasons=[],
            temporalMode=temporal_mode,
        )

    # ── Reading canonical truth (tenant-scoped) ──────────────────────────────

    async def _load_outcomes(self, request: ProjectionRequest) -> list[Outcome]:
        """Outcome rows for the request, strictly scoped to its tenant."""
        store = self._outcome_store
        if store is None:
            store = _measurement_outcome_store()
        if store is None:
            # No backing source available at runtime: degrade to an empty set.
            # The sections render as typed `missing`; the plane stays up.
            return []
        return await store.list_outcomes(request.tenantId, request.subject)

    # ── Rendering ────────────────────────────────────────────────────────────

    def _build_sections(
        self,
        request: ProjectionRequest,
        outcomes: list[Outcome],
        temporal_mode: str,
        temporal: Optional[ProjectionDependencyState],
        warnings: list[str],
    ) -> list[ProjectionSection]:
        store_present = self._outcome_store is not None
        evidence = _collect_evidence(outcomes)
        findings = self._derive_findings(outcomes)

        availability = _availability(store_present=store_present, present=bool(outcomes))
        evidence_availability = _availability(
            store_present=store_present, present=bool(evidence)
        )
        findings_availability = _availability(
            store_present=store_present, present=bool(findings)
        )
        summary_deps = []
        if temporal is not None:
            summary_deps = [
                {"projectionId": temporal.projectionId, "state": temporal.state}
            ]

        sections = [
            ProjectionSection(
                id="summary",
                state=availability,
                title=_SECTION_TITLES["summary"],
                content={
                    "subject": request.subject.model_dump(),
                    "tenantId": request.tenantId,
                    "outcomeCount": len(outcomes),
                    "stateDistribution": _state_distribution(outcomes),
                    "temporalMode": temporal_mode,
                    "dependencyState": summary_deps,
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="state",
                state=availability,
                title=_SECTION_TITLES["state"],
                content={"distribution": _state_distribution(outcomes)},
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="evidence",
                state=evidence_availability,
                title=_SECTION_TITLES["evidence"],
                content={
                    "evidence": [ref.model_dump() for ref in evidence],
                    "evidenceCount": len(evidence),
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="outcomes",
                state=availability,
                title=_SECTION_TITLES["outcomes"],
                content={
                    "outcomes": [outcome.model_dump() for outcome in outcomes],
                },
                warnings=warnings or None,
            ),
            ProjectionSection(
                id="findings",
                state=findings_availability,
                title=_SECTION_TITLES["findings"],
                content={"findings": findings},
                warnings=warnings or None,
            ),
        ]

        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [s for s in sections if s.id in wanted]
        return sections

    def _build_claims(
        self,
        request: ProjectionRequest,
        outcomes: list[Outcome],
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for outcome in outcomes:
            claims.append(
                ClaimEnvelope(
                    id=f"outcome.{outcome.id}",
                    kind="outcome_state",
                    subject=request.subject,
                    evidenceRefs=outcome.evidence_refs,
                    claims=[f"outcome {outcome.id!r} is {outcome.state.value}"],
                )
            )
        completion = [
            o for o in outcomes if o.definition_ref == _JOURNEY_COMPLETION_DEFINITION_REF
        ]
        if completion:
            achieved = [o for o in completion if o.achieved_at is not None]
            rate = len(achieved) / len(completion)
            claims.append(
                ClaimEnvelope(
                    id="metric.journey_completion_rate",
                    kind="metric",
                    subject=request.subject,
                    evidenceRefs=_collect_evidence(completion),
                    claims=[f"journey completion rate: {rate:.4f}"],
                )
            )
        return claims

    def _derive_findings(self, outcomes: list[Outcome]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        completion = [
            o for o in outcomes if o.definition_ref == _JOURNEY_COMPLETION_DEFINITION_REF
        ]
        if completion:
            achieved = [o for o in completion if o.achieved_at is not None]
            rate = len(achieved) / len(completion)
            findings.append(
                {
                    "metric": "journey_completion_rate",
                    "definitionRef": _JOURNEY_COMPLETION_DEFINITION_REF,
                    "completed": len(achieved),
                    "total": len(completion),
                    "rate": round(rate, 4),
                }
            )
        if outcomes:
            terminal = [
                o
                for o in outcomes
                if o.state in (OutcomeState.FINAL, OutcomeState.SUPERSEDED)
            ]
            findings.append(
                {
                    "finding": "finality_coverage",
                    "terminalOutcomes": len(terminal),
                    "totalOutcomes": len(outcomes),
                }
            )
        return findings

    @staticmethod
    def _page_slice(
        request: ProjectionRequest, outcomes: list[Outcome]
    ) -> tuple[list[Outcome], Optional[PageInfo]]:
        """Apply lightweight cursor-free paging to the render set.

        Capping the RENDER set at ``page.limit`` keeps ``hasNextPage`` honest
        while the full tenant-scoped set stays available to the caller via a
        follow-up page. No page -> full set, no page metadata.
        """
        if request.page is None:
            return outcomes, None
        limit = request.page.limit
        return (
            outcomes[:limit],
            PageInfo(
                hasNextPage=len(outcomes) > limit,
                totalEstimate=len(outcomes),
            ),
        )


# ── Module helpers ───────────────────────────────────────────────────────────


def _dependency_state(
    context: ProjectionContext, projection_id: str
) -> Optional[ProjectionDependencyState]:
    for dep in context.dependencyState:
        if dep.projectionId == projection_id:
            return dep
    return None


def _effective_temporal_mode(
    requested: Optional[str], temporal: Optional[ProjectionDependencyState]
) -> str:
    """Resolve the temporal mode, degrading comparison when temporal360 is
    unavailable (typed degradation, never a raise)."""
    if requested is None:
        return "window"
    if requested == "compare" and temporal is not None and temporal.state != "available":
        return "window"
    return requested


def _availability(*, store_present: bool, present: bool) -> str:
    if present:
        return "available"
    return "empty" if store_present else "missing"


def _state_distribution(outcomes: list[Outcome]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for outcome in outcomes:
        key = outcome.state.value
        distribution[key] = distribution.get(key, 0) + 1
    return dict(sorted(distribution.items()))


def _collect_evidence(outcomes: list[Outcome]) -> list[EvidenceRef]:
    """Deduplicated, order-stable evidence refs across outcome rows."""
    seen: set[str] = set()
    refs: list[EvidenceRef] = []
    for outcome in outcomes:
        for ref in outcome.evidence_refs:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
    return refs


def register_provider(registry: ProviderRegistry) -> str:
    """Register the Outcome360 provider on a ``ProviderRegistry`` instance.

    Returns the registered projection id (``"outcome360"``). Deliberately does
    NOT auto-register on the global
    ``shared.intelligence_projections.registry.projection_registry`` at import
    time — tests and embeddings use fresh ``ProviderRegistry()`` instances, and
    registration order stays explicit.
    """
    return registry.register(
        Outcome360Provider(),
        source="services/measurement/outcome",
    )


__all__ = [
    "Outcome360Provider",
    "OutcomeStore",
    "register_provider",
]
