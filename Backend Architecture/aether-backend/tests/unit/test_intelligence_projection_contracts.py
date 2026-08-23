"""Unit tests for the shared intelligence-projection contracts (P0.4, group 11).

The Python twin of ``packages/shared/intelligence-projection.ts`` must stay in
lockstep with the generated registry vocabulary (SectionState / ProjectionId /
ProjectionSubjectKind / ProjectionRegistryState parity), validate required
fields (subject, tenantId, generatedAt, and the required list fields), reject
unknown fields (the projection plane fails closed, unlike ContractModel),
round-trip the contract version, and expose a catchable typed error hierarchy
rooted at ``ProjectionError``.

The C5 blocker regression: a provider for campaign360 / economic360 / outcome360
/ population360 / connection360 / ... MUST be able to construct a
``ProjectionRequest.subject`` — ``ProjectionSubject.kind`` is the projection
plane's own vocab, not ``EntityRef.kind``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections import (  # noqa: E402
    ClaimEnvelope,
    ContractVersionIncompatible,
    DependencyUnavailable,
    DuplicateProjection,
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_IMPLEMENTATION_STATES,
    PROJECTION_SECTION_STATES,
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionError,
    ProjectionId,
    ProjectionNotFound,
    ProjectionNotImplemented,
    ProjectionRegistryState,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProjectionSubjectKind,
    SectionState,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from services.operational_intelligence.models import (  # noqa: E402
    EvidenceRef,
    TimeRangeFilter,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _subject(kind: str = "entity", ident: str = "ent_1") -> ProjectionSubject:
    return ProjectionSubject(kind=kind, id=ident)


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "profile360",
        "tenantId": "tenant-a",
        "subject": _subject(),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _result(**overrides: object) -> ProjectionResult:
    values: dict[str, object] = {
        "projectionId": "profile360",
        "tenantId": "tenant-a",
        "contractVersion": INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        "generatedAt": "2026-08-23T12:00:00Z",
        "sections": [
            ProjectionSection(id="summary", state="available", title="Summary"),
        ],
        "claims": [
            ClaimEnvelope(
                id="claim_1",
                kind="observation",
                subject=_subject(),
                evidenceRefs=[EvidenceRef(id="ev_1", type="event", source="s1")],
                claims=["active"],
            ),
        ],
        "dependencyState": [
            ProjectionDependencyState(
                projectionId="temporal360", state="available"
            ),
        ],
        "degradedReasons": [],
    }
    values.update(overrides)
    return ProjectionResult(**values)


# ---------------------------------------------------------------------------
# Vocab parity with the generated registry
# ---------------------------------------------------------------------------

def test_section_state_covers_exactly_the_generated_states() -> None:
    # The 6 section states are generated; SectionState must match exactly.
    assert len(PROJECTION_SECTION_STATES) == 6
    assert set(get_args(SectionState)) == set(PROJECTION_SECTION_STATES)
    assert tuple(get_args(SectionState)) == PROJECTION_SECTION_STATES


def test_projection_id_derived_from_generated_ids() -> None:
    assert tuple(get_args(ProjectionId)) == INTELLIGENCE_PROJECTION_IDS


def test_projection_subject_kind_matches_generated_registry() -> None:
    expected = tuple(
        sorted(
            {
                kind
                for definition in INTELLIGENCE_PROJECTION_DEFINITIONS.values()
                for kind in definition["subjectKinds"]
            }
        )
    )
    assert len(expected) == 9  # entity/relationship/campaign/episode/population/source/connection/cluster/agent
    assert tuple(get_args(ProjectionSubjectKind)) == expected


def test_registry_state_matches_generated_implementation_states() -> None:
    assert tuple(get_args(ProjectionRegistryState)) == PROJECTION_IMPLEMENTATION_STATES


# ---------------------------------------------------------------------------
# ProjectionSubject — the C5 blocker
# ---------------------------------------------------------------------------

def test_campaign360_subject_validates() -> None:
    # THE C5 blocker: a provider for a non-entity projection must be able to
    # build a ProjectionRequest.subject from the projection-plane vocab.
    req = ProjectionRequest(
        projectionId="campaign360",
        tenantId="tenant-a",
        subject=ProjectionSubject(kind="campaign", id="cmp_1"),
    )
    assert req.projectionId == "campaign360"
    assert req.subject.kind == "campaign"
    assert req.subject.id == "cmp_1"


def test_connection360_subject_validates() -> None:
    req = ProjectionRequest(
        projectionId="connection360",
        tenantId="tenant-a",
        subject=ProjectionSubject(kind="connection", id="conn_1"),
    )
    assert req.subject.kind == "connection"


def test_projection_subject_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        ProjectionSubject(kind="silly_kind", id="x")


# ---------------------------------------------------------------------------
# Required-field validation + fail-closed extra fields
# ---------------------------------------------------------------------------

def test_request_requires_subject() -> None:
    with pytest.raises(ValidationError):
        ProjectionRequest(projectionId="profile360", tenantId="tenant-a")


def test_request_requires_tenant_id() -> None:
    with pytest.raises(ValidationError):
        ProjectionRequest(projectionId="profile360", subject=_subject())


def test_request_accepts_optional_fields() -> None:
    req = _request(
        timeRange=TimeRangeFilter(
            from_="2026-01-01T00:00:00Z", to="2026-08-01T00:00:00Z"
        ),
        includeSections=["summary", "timeline"],
        includeClaims=True,
    )
    assert req.tenantId == "tenant-a"
    assert req.subject.id == "ent_1"
    assert req.includeSections == ["summary", "timeline"]
    assert req.includeClaims is True
    assert req.timeRange is not None and req.timeRange.to == "2026-08-01T00:00:00Z"


def test_request_rejects_extra_fields() -> None:
    # The projection plane fails closed on typos (unlike ContractModel).
    with pytest.raises(ValidationError):
        ProjectionRequest(
            projectionId="profile360",
            tenantId="tenant-a",
            subject=_subject(),
            tenatId="typo",  # not a declared field
        )


def test_result_requires_generated_at() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="profile360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            degradedReasons=[],
        )


def test_result_requires_list_fields() -> None:
    # MINOR-4: sections/claims/dependencyState/degradedReasons are required.
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="profile360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            generatedAt="2026-08-23T12:00:00Z",
        )


def test_context_rejects_unknown_registry_state() -> None:
    with pytest.raises(ValidationError):
        ProjectionContext(
            projectionId="profile360",
            tenantId="tenant-a",
            registryState="not_a_state",
            dependencyState=[],
            warnings=[],
        )


# ---------------------------------------------------------------------------
# ProjectionResult round-trip
# ---------------------------------------------------------------------------

def test_result_contract_version_round_trips() -> None:
    result = _result()
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    dumped = result.model_dump()
    assert dumped["contractVersion"] == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    reloaded = ProjectionResult(**dumped)
    assert reloaded.contractVersion == result.contractVersion
    assert reloaded.generatedAt == result.generatedAt
    assert reloaded.sections[0].state == "available"
    assert reloaded.claims[0].evidenceRefs[0].id == "ev_1"
    assert reloaded.claims[0].subject.kind == "entity"


def test_context_builds_with_dependency_state() -> None:
    context = ProjectionContext(
        projectionId="profile360",
        tenantId="tenant-a",
        registryState="in_flight",
        dependencyState=[
            ProjectionDependencyState(
                projectionId="risk360", state="not_applicable", reason="optional"
            ),
        ],
        warnings=["temporal replay not configured"],
    )
    assert context.registryState == "in_flight"
    assert context.dependencyState[0].state == "not_applicable"
    assert context.warnings == ["temporal replay not configured"]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

def test_projection_errors_importable_and_catchable() -> None:
    err = ProjectionNotFound(
        "no provider registered for profile360", projection_id="profile360"
    )
    assert isinstance(err, ProjectionError)
    assert err.message == "no provider registered for profile360"
    assert err.projection_id == "profile360"

    for exc in (
        DuplicateProjection("already registered"),
        DependencyUnavailable("hard dependency unavailable"),
        ProjectionNotImplemented("registered but not implemented"),
    ):
        assert isinstance(exc, ProjectionError)
        assert exc.context == {}
        assert exc.projection_id is None
        assert exc.version is None


def test_contract_version_incompatible_carries_version() -> None:
    exc = ContractVersionIncompatible(
        "provider contract version 9.9.9 incompatible", version="9.9.9"
    )
    assert isinstance(exc, ProjectionError)
    assert exc.version == "9.9.9"
    assert exc.message == "provider contract version 9.9.9 incompatible"


def test_projection_not_found_is_caught_as_base_error() -> None:
    try:
        raise ProjectionNotFound("boom", projection_id="profile360")
    except ProjectionError as caught:
        assert isinstance(caught, ProjectionNotFound)
        assert caught.projection_id == "profile360"
