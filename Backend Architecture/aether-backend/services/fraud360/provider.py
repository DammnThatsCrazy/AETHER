"""Fraud360 intelligence-projection provider (Phase 4 of Risk/Fraud360).

Fraud360 is a **domain-synthesis** intelligence projection over canonical Aether
truth — never a competing system of record (ADR-010). This provider renders the
fraud-synthesis surface for a subject (entity / relationship / agent) from the
Phase-3 ``services/fraud360`` store: tenant-scoped :class:`FraudHypothesis`
records whose lifecycle + claim vocabulary are typed by
``services/fraud360/contracts.py`` (:class:`FraudHypothesisState`, the
consolidated ``EpistemicStatus``, and the no-silent-escalation rule enforced by
:class:`FraudHypothesisStateMachine` at the storage boundary).

The provider is a read-only, fail-isolated, tenant-scoped projection:

* It raises ONLY :class:`ProjectionError` subclasses on failure; the registry
  fail-isolates any other exception (in practice it degrades rather than raises).
* **No-silent-escalation is echoed, not overridden.** A hypothesis is NEVER
  rendered stronger than its stored contract state / claim permits: this
  provider echoes each hypothesis's stored ``state`` + ``claim_state`` verbatim.
  A ``derived``/``inferred``/``predicted``/``correlated``/``attributed``
  suspicion can never surface as ``confirmed``/``verified``/``causally_supported``
  because that rule lives in the state machine and the store; the provider is a
  read-only echo, never an override.
* **Contradictions are first-class.** The ``evidence`` section carries both the
  ``supporting`` and the ``contradictory_evidence_refs`` lists from each
  hypothesis, reusing canonical :class:`EvidenceRef`.
* **Honest absence.** No hypotheses for the subject is an honest ``empty`` /
  ``missing`` outcome (families involved, hypothesis count/state, materiality),
  never a fabricated row.
* **Dependency degradation.** The registry declares ``projectionDependencies:
  [profile360, risk360]``. When a contributing sibling is missing/unregistered
  in ``context.dependencyState`` the provider degrades the risk-assessment
  contributions to synthesis honestly — a hypothesis set without contributing
  risk assessments is PARTIAL, surfaced as a typed ``degraded`` section — never
  a projection failure. ``dependencyState`` is echoed verbatim on the result.
* **Fail isolation.** Any source exception degrades its section content-free
  (never the exception message, never a leak). Tenant scope is
  server-authoritative (the provider re-filters every hypothesis by the
  requesting tenant AND subject).

The full findings handoff — synthesis of risk assessments / network clusters /
flow traces / decisions into NEW material hypotheses — is Phase 6 (wired through
the :class:`FraudSourceReader` seam). Phase 4 surfaces material hypotheses that
ALREADY exist in the store as finding candidates, and honest ``missing`` /
``empty`` states otherwise.

Imports stay lazy/defensive: importing this module must never require a database,
a store backend, or any heavy canonical service. All store reads happen inside
the injected source reader (default :class:`RepositoryFraudSourceReader`), each
wrapped so an unavailable backing source degrades its sections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Protocol

# Lightweight plane imports — always importable.
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
from shared.intelligence_projections.registry import ProviderRegistry

# Fraud360 domain contracts for this slice (reused, never re-declared).
from services.fraud360.contracts import FraudHypothesis, FraudHypothesisState
from services.operational_intelligence.models import EvidenceRef

# The projection id, surfaced for the routes layer and any wiring consumer.
PROJECTION_ID = "fraud360"

# Sections the registry declares for fraud360 (must equal the registry row's
# outputSections set: evidence, findings, health, state, summary).
OUTPUT_SECTIONS: tuple[str, ...] = ("summary", "state", "evidence", "findings", "health")

# Registry-declared sibling projections fraud360 degrades for honestly while they
# are unavailable (profile360 / risk360). Each entry maps the section whose
# risk-assessment enrichment depends on that sibling projection.
SECTION_DEPENDENCIES: dict[str, str] = {
    "summary": "risk360",
    "state": "risk360",
    "findings": "risk360",
}

# Every contributing synthesis dependency (both are hard projection
# dependencies on the fraud360 registry row).
SYNTHESIS_DEPENDENCIES: tuple[str, ...] = ("profile360", "risk360")

# Lifecycle band at which a stored hypothesis is a "material" finding candidate.
_MATERIAL_HYPOTHESIS_STATES: frozenset[FraudHypothesisState] = frozenset(
    {
        FraudHypothesisState.MATERIAL,
        FraudHypothesisState.INVESTIGATING,
        FraudHypothesisState.CONFIRMED,
    }
)


def _dependency_missing(dep_state: list[Any], projection_id: str) -> bool:
    """True when a sibling projection is missing or not yet available."""
    dep = next((d for d in dep_state if d.projectionId == projection_id), None)
    return dep is None or dep.state != "available"


def _synthesis_degraded(dep_state: list[Any]) -> bool:
    """True when a contributing synthesis dependency is missing/unregistered."""
    return any(_dependency_missing(dep_state, pid) for pid in SYNTHESIS_DEPENDENCIES)


def _missing_synthesis_dependencies(dep_state: list[Any]) -> list[str]:
    """Names of the contributing synthesis dependencies that are unavailable."""
    return [pid for pid in SYNTHESIS_DEPENDENCIES if _dependency_missing(dep_state, pid)]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FraudSourceReader(Protocol):
    """Canonical fraud-synthesis read seam for the provider.

    Implementations MUST be tenant-scoped: the provider trusts nothing and
    re-filters every returned hypothesis by the requesting tenant AND subject as
    a server-authoritative backstop. A reader that cannot reach its backing store
    returns ``[]`` (the provider degrades the affected sections) — never raises,
    never fabricates. Phase 6 wires real synthesis (risk assessments / network
    clusters / flow traces / decisions) through this seam.
    """

    async def hypotheses(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[FraudHypothesis]:
        """FraudHypothesis records stored for the tenant + subject (honest [])."""
        ...


class RepositoryFraudSourceReader:
    """Default canonical reader over the Phase-3 ``FraudHypothesisRepository``.

    Reads the tenant's ``fraud_hypotheses`` JSONB table (in-memory when
    ``AETHER_ENV=local``) defensively and filters to the subject. A backing-store
    failure returns ``[]`` — the projection degrades, it never crashes.
    """

    async def hypotheses(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> list[FraudHypothesis]:
        try:
            from services.fraud360.store import FraudHypothesisRepository

            rows = await FraudHypothesisRepository().list(tenant_id, limit=500)
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        return [
            h
            for h in rows
            if h.tenant_id == tenant_id
            and h.subject_kind == subject.kind
            and h.subject_id == subject.id
        ]


def _pattern_family(pattern_id: str) -> Optional[str]:
    """Family name for a registered FraudPattern id, or None when unknown."""
    try:
        from services.fraud360.patterns import fraud_pattern
    except Exception:  # noqa: BLE001 - pattern registry unreadable -> honest None
        return None
    pattern = fraud_pattern(pattern_id)
    return pattern.family if pattern is not None else None


def _families(hypotheses: list[FraudHypothesis]) -> list[str]:
    """Distinct families involved across every matched pattern (sorted)."""
    families: set[str] = set()
    for hypothesis in hypotheses:
        for pattern_id in hypothesis.matched_pattern_ids:
            family = _pattern_family(pattern_id)
            if family:
                families.add(family)
    return sorted(families)


def _primary_family(hypothesis: FraudHypothesis) -> Optional[str]:
    """The first resolvable family for a hypothesis (None when unresolvable)."""
    for pattern_id in hypothesis.matched_pattern_ids:
        family = _pattern_family(pattern_id)
        if family:
            return family
    return None


def _state_counts(hypotheses: list[FraudHypothesis]) -> dict[str, int]:
    """Distribution over the FraudHypothesisState lifecycle vocabulary."""
    counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        counts[hypothesis.state.value] = counts.get(hypothesis.state.value, 0) + 1
    return counts


def _claim_counts(hypotheses: list[FraudHypothesis]) -> dict[str, int]:
    """Distribution over the consolidated EpistemicStatus claim vocabulary."""
    counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        counts[hypothesis.claim_state.value] = (
            counts.get(hypothesis.claim_state.value, 0) + 1
        )
    return counts


def _max_materiality(hypotheses: list[FraudHypothesis]) -> Optional[float]:
    """Highest declared materiality across the hypotheses (None when none set)."""
    present = [h.materiality for h in hypotheses if h.materiality is not None]
    return max(present) if present else None


def _dedup_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Deduplicate canonical EvidenceRefs by (id, source), preserving order."""
    seen: set[tuple[str, str]] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.id, ref.source)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _material_candidates(hypotheses: list[FraudHypothesis]) -> list[FraudHypothesis]:
    """Hypotheses whose stored lifecycle state has reached material significance."""
    return [h for h in hypotheses if h.state in _MATERIAL_HYPOTHESIS_STATES]


def _pattern_registry_health() -> dict[str, Any]:
    """Read-only pattern-registry posture (registered patterns + families)."""
    try:
        from services.fraud360.patterns import FRAUD_PATTERNS

        patterns = list(FRAUD_PATTERNS)
        return {
            "registeredPatterns": len(patterns),
            "families": len({p.family for p in patterns}),
        }
    except Exception:  # noqa: BLE001 - pattern registry unreadable -> honest None
        return {"registeredPatterns": None, "families": None}


class Fraud360Provider:
    """Intelligence-projection provider for ``fraud360`` (read-only).

    Echoes tenant-scoped ``FraudHypothesis`` records — lifecycle state and claim
    state verbatim — into the registry's typed sections. Never escalates, never
    fabricates, never writes, and degrades honestly when a contributing sibling
    projection (``profile360`` / ``risk360``) is unavailable.
    """

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, sources: Optional[FraudSourceReader] = None) -> None:
        # Injected canonical reader (test seam); default reads the repository.
        self._sources = sources if sources is not None else RepositoryFraudSourceReader()

    # ── IntelligenceProjectionProvider ─────────────────────────────────────

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one read-only Fraud360 projection over canonical fraud hypotheses."""
        tenant_id = request.tenantId
        rows, read_ok = await self._safe_hypotheses(tenant_id, request.subject)
        hypotheses = [
            h
            for h in rows
            if h.tenant_id == tenant_id
            and h.subject_kind == request.subject.kind
            and h.subject_id == request.subject.id
        ]

        dep_state = context.dependencyState
        sections = [
            self._summary_section(request, hypotheses, dep_state, read_ok),
            self._state_section(hypotheses, dep_state, read_ok),
            self._evidence_section(hypotheses, read_ok),
            self._findings_section(request, hypotheses, dep_state, read_ok),
            self._health_section(dep_state, read_ok),
        ]
        claims = self._build_claims(request, hypotheses)

        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=tenant_id,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(dep_state),
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
        )

    # ── Section builders ───────────────────────────────────────────────────

    def _summary_section(
        self,
        request: ProjectionRequest,
        hypotheses: list[FraudHypothesis],
        dep_state: list[Any],
        read_ok: bool,
    ) -> ProjectionSection:
        """summary — synthesis posture: families, counts, state, materiality."""
        state: str = "available"
        if not read_ok:
            state = "missing"
        elif not hypotheses:
            state = "empty"
        elif _synthesis_degraded(dep_state):
            state = "degraded"

        warnings: list[str] = []
        if state == "degraded":
            missing = ", ".join(_missing_synthesis_dependencies(dep_state))
            warnings.append(
                f"fraud synthesis is partial: contributing risk-assessment "
                f"dependency missing ({missing})"
            )

        subject = {"kind": request.subject.kind, "id": request.subject.id}
        if not read_ok:
            # Hypothesis count is UNKNOWN, never a fabricated zero.
            content: dict[str, Any] = {
                "tenantId": request.tenantId,
                "subject": subject,
                "hypothesisCount": None,
                "families": None,
                "stateCounts": None,
                "materiality": None,
                "synthesisState": "unavailable",
            }
        else:
            content = {
                "tenantId": request.tenantId,
                "subject": subject,
                "hypothesisCount": len(hypotheses),
                "families": _families(hypotheses),
                "stateCounts": _state_counts(hypotheses),
                "materiality": _max_materiality(hypotheses),
                "synthesisState": "observed" if hypotheses else "absent",
                "missingDependencies": (
                    _missing_synthesis_dependencies(dep_state) or None
                ),
            }
        return ProjectionSection(
            id="summary",
            state=state,  # type: ignore[arg-type]
            title="Fraud summary",
            content=content,
            warnings=warnings or None,
        )

    def _state_section(
        self,
        hypotheses: list[FraudHypothesis],
        dep_state: list[Any],
        read_ok: bool,
    ) -> ProjectionSection:
        """state — stored hypothesis/family states echoed verbatim (never escalated)."""
        state: str = "available"
        if not read_ok:
            state = "missing"
        elif not hypotheses:
            state = "empty"
        elif _synthesis_degraded(dep_state):
            state = "degraded"

        warnings: list[str] = []
        if state == "degraded":
            missing = ", ".join(_missing_synthesis_dependencies(dep_state))
            warnings.append(
                f"fraud hypothesis state is degraded: contributing "
                f"risk-assessment dependency missing ({missing})"
            )

        if not read_ok:
            content: dict[str, Any] = {"hypothesisStates": None}
        else:
            content = {
                "hypothesisStates": [
                    {
                        "hypothesisId": h.hypothesis_id,
                        "state": h.state.value,
                        "claimState": h.claim_state.value,
                        "confidence": h.confidence,
                        "materiality": h.materiality,
                        "family": _primary_family(h),
                    }
                    for h in hypotheses
                ],
                "stateCounts": _state_counts(hypotheses),
                "claimCounts": _claim_counts(hypotheses),
            }
        return ProjectionSection(
            id="state",
            state=state,  # type: ignore[arg-type]
            title="Fraud hypothesis state",
            content=content,
            warnings=warnings or None,
        )

    def _evidence_section(
        self,
        hypotheses: list[FraudHypothesis],
        read_ok: bool,
    ) -> ProjectionSection:
        """evidence — supporting AND contradictory EvidenceRefs (both first-class)."""
        if not read_ok:
            return ProjectionSection(
                id="evidence",
                state="missing",  # type: ignore[arg-type]
                title="Evidence",
                content={"supporting": None, "contradictory": None},
            )
        supporting = _dedup_refs(
            [ref for h in hypotheses for ref in h.evidence_refs]
        )
        contradictory = _dedup_refs(
            [ref for h in hypotheses for ref in h.contradictory_evidence_refs]
        )
        return ProjectionSection(
            id="evidence",
            state="available" if (supporting or contradictory) else "empty",  # type: ignore[arg-type]
            title="Evidence",
            content={
                "supportingCount": len(supporting),
                "contradictoryCount": len(contradictory),
                "supporting": [ref.model_dump(mode="json") for ref in supporting],
                "contradictory": [ref.model_dump(mode="json") for ref in contradictory],
            },
        )

    def _findings_section(
        self,
        request: ProjectionRequest,
        hypotheses: list[FraudHypothesis],
        dep_state: list[Any],
        read_ok: bool,
    ) -> ProjectionSection:
        """findings — stored material hypotheses surface as candidates only.

        The full findings handoff (synthesis of risk assessments / network
        clusters / flow traces / decisions into new material hypotheses) is
        Phase 6. Today, material hypotheses already present in the store surface
        as finding candidates; otherwise the section is an honest ``empty`` /
        ``missing`` state.
        """
        candidates = _material_candidates(hypotheses) if read_ok else []
        state: str = "available"
        if not read_ok:
            state = "missing"
        elif not candidates:
            state = "empty"
        elif _synthesis_degraded(dep_state):
            state = "degraded"

        warnings: list[str] = []
        if state == "degraded":
            missing = ", ".join(_missing_synthesis_dependencies(dep_state))
            warnings.append(
                f"findings are partial: contributing risk-assessment dependency "
                f"missing ({missing})"
            )

        return ProjectionSection(
            id="findings",
            state=state,  # type: ignore[arg-type]
            title="Fraud findings",
            content={
                "tenantId": request.tenantId,
                "candidates": [
                    {
                        "hypothesisId": h.hypothesis_id,
                        "state": h.state.value,
                        "claimState": h.claim_state.value,
                        "family": _primary_family(h),
                        "materiality": h.materiality,
                        "confidence": h.confidence,
                        "matchedPatternIds": list(h.matched_pattern_ids),
                        "evidenceRefs": [
                            ref.model_dump(mode="json") for ref in h.evidence_refs
                        ],
                    }
                    for h in candidates
                ],
                "candidatesCount": len(candidates),
                "handoffNote": (
                    "full findings synthesis is Phase 6; candidates echo stored "
                    "material hypotheses only"
                ),
            },
            warnings=warnings or None,
        )

    def _health_section(
        self,
        dep_state: list[Any],
        read_ok: bool,
    ) -> ProjectionSection:
        """health — read-only plane posture + pattern-registry + dependency echo."""
        return ProjectionSection(
            id="health",
            state="available" if read_ok else "degraded",  # type: ignore[arg-type]
            title="Fraud 360 health",
            content={
                "projection": self.projection_id,
                "graphMutationPolicy": self.graph_mutation_policy,
                "store": "reachable" if read_ok else "unreachable",
                "patternRegistry": _pattern_registry_health(),
                "dependencyState": [
                    {"projectionId": d.projectionId, "state": d.state}
                    for d in dep_state
                ],
            },
        )

    # ── Claims ─────────────────────────────────────────────────────────────

    def _build_claims(
        self,
        request: ProjectionRequest,
        hypotheses: list[FraudHypothesis],
    ) -> list[ClaimEnvelope]:
        """Evidence-grounded claims echoing stored hypothesis states (never escalate).

        Every claim carries canonical ``EvidenceRef`` grounds (supporting
        evidence only) — a claim that cannot be grounded is not emitted.
        """
        claims: list[ClaimEnvelope] = []
        subject = ProjectionSubject(kind=request.subject.kind, id=request.subject.id)
        supporting = _dedup_refs(
            [ref for h in hypotheses for ref in h.evidence_refs]
        )

        if hypotheses and supporting:
            claims.append(
                ClaimEnvelope(
                    id="summary.hypotheses_recorded",
                    kind="fraud_synthesis",
                    subject=subject,
                    evidenceRefs=supporting,
                    claims=[
                        f"{len(hypotheses)} fraud hypotheses recorded for "
                        f"{subject.kind}:{subject.id}"
                    ],
                    confidence=None,
                )
            )

        for h in hypotheses:
            if not h.evidence_refs:
                continue
            claims.append(
                ClaimEnvelope(
                    id=f"state.{h.hypothesis_id}",
                    kind="fraud_hypothesis",
                    subject=subject,
                    evidenceRefs=list(h.evidence_refs),
                    claims=[
                        f"hypothesis {h.hypothesis_id} is recorded in state "
                        f"{h.state.value!r} with claim state "
                        f"{h.claim_state.value!r}"
                    ],
                    confidence=h.confidence,
                )
            )
        return claims

    # ── Canonical read helper (defensive) ──────────────────────────────────

    async def _safe_hypotheses(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
    ) -> tuple[list[FraudHypothesis], bool]:
        """Hypotheses for the subject; (rows, read_ok). A reader failure degrades."""
        try:
            rows = await self._sources.hypotheses(
                tenant_id=tenant_id, subject=subject
            )
            return list(rows), True
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return [], False


def build_projection_request(
    *,
    projection_id: str,
    tenant_id: str,
    subject: ProjectionSubject,
) -> ProjectionRequest:
    """Build a strict :class:`ProjectionRequest` for a fraud360 route handler."""
    return ProjectionRequest(
        projectionId=projection_id,
        tenantId=tenant_id,
        subject=subject,
    )


def register_provider(registry: ProviderRegistry) -> None:
    """Register :class:`Fraud360Provider` on a provider registry.

    Deliberately NOT called at import time: the global ``projection_registry``
    is only mutated by the runtime wiring layer, never by provider modules.
    """
    registry.register(Fraud360Provider(), source="services/fraud360")


__all__ = [
    "Fraud360Provider",
    "FraudSourceReader",
    "FraudHypothesis",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryFraudSourceReader",
    "SECTION_DEPENDENCIES",
    "SYNTHESIS_DEPENDENCIES",
    "build_projection_request",
    "register_provider",
]
