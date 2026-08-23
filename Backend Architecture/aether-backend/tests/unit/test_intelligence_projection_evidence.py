"""Evidence-reuse tests for the intelligence projection plane (P0.5, group 9).

Projections reuse, never redefine: ``EvidenceRef`` is the canonical
operational-intelligence primitive (``services.operational_intelligence.models``)
imported by the shared contracts. A provider's claims carry those canonical
``EvidenceRef`` objects inside a ``ClaimEnvelope`` whose ``subject`` is the
projection-plane ``ProjectionSubject``. This pins that no projection-plane
redefinition exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import shared.intelligence_projections.contracts as contracts_mod  # noqa: E402
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ClaimEnvelope,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "profile360",
        "tenantId": "tenant-a",
        "subject": ProjectionSubject(kind="entity", id="ent_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


class _EvidenceProvider:
    """profile360 provider whose claims carry canonical EvidenceRef objects."""

    projection_id = "profile360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[
                ClaimEnvelope(
                    id="claim_1",
                    kind="observation",
                    subject=ProjectionSubject(kind="entity", id=request.subject.id),
                    evidenceRefs=[
                        EvidenceRef(
                            id="ev_1",
                            type="event",
                            source="source_a",
                            observedAt="2026-08-01T00:00:00Z",
                            confidence=0.9,
                        ),
                        EvidenceRef(
                            id="ev_2",
                            type="event",
                            source="source_b",
                            confidence=0.8,
                        ),
                    ],
                    claims=["was active during the window"],
                    confidence=0.9,
                ),
            ],
            dependencyState=context.dependencyState,  # type: ignore[attr-defined]
            generatedAt="2026-08-23T12:00:00Z",
            degradedReasons=[],
        )


# ---------------------------------------------------------------------------
# The contracts reuse the canonical EvidenceRef (never a redefinition)
# ---------------------------------------------------------------------------

def test_contracts_reuse_canonical_evidence_ref() -> None:
    # contracts.py imports EvidenceRef from services.operational_intelligence.models.
    assert contracts_mod.EvidenceRef is EvidenceRef


@pytest.mark.asyncio
async def test_provider_claims_carry_canonical_evidence_ref_instances() -> None:
    registry = ProviderRegistry()
    registry.register(_EvidenceProvider())

    result = await registry.project("profile360", _request())

    assert isinstance(result, ProjectionResult)
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert isinstance(claim, ClaimEnvelope)
    # subject is the projection-plane vocabulary.
    assert isinstance(claim.subject, ProjectionSubject)
    assert claim.subject.kind == "entity"
    assert claim.subject.id == "ent_1"
    assert claim.kind == "observation"
    assert claim.claims == ["was active during the window"]
    assert claim.confidence == 0.9

    # Every evidence ref is an INSTANCE of the canonical EvidenceRef — not a
    # projection-plane redefinition.
    assert len(claim.evidenceRefs) == 2
    for evidence in claim.evidenceRefs:
        assert isinstance(evidence, EvidenceRef)
        assert type(evidence).__module__ == "services.operational_intelligence.models"

    first = claim.evidenceRefs[0]
    assert first.id == "ev_1"
    assert first.type == "event"
    assert first.source == "source_a"
    assert first.observedAt == "2026-08-01T00:00:00Z"
    assert first.confidence == 0.9

    # The result round-trips through pydantic with the canonical refs intact.
    reloaded = ProjectionResult(**result.model_dump())
    reloaded_evidence = reloaded.claims[0].evidenceRefs[0]
    assert reloaded_evidence.id == "ev_1"
    assert isinstance(reloaded_evidence, EvidenceRef)
    assert type(reloaded_evidence).__module__ == "services.operational_intelligence.models"


@pytest.mark.asyncio
async def test_evidence_survives_repeated_projections() -> None:
    registry = ProviderRegistry()
    registry.register(_EvidenceProvider())

    first = await registry.project("profile360", _request())
    second = await registry.project("profile360", _request())

    # Identical evidence across runs — no shared-state mutation.
    assert [e.id for e in first.claims[0].evidenceRefs] == ["ev_1", "ev_2"]
    assert [e.id for e in second.claims[0].evidenceRefs] == ["ev_1", "ev_2"]
    assert first.claims[0] == second.claims[0]
