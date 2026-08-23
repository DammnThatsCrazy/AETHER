"""Unit tests for the shared intelligence-projection contracts (P0.4, group 11).

The Python twin of ``packages/shared/intelligence-projection.ts`` must stay in
lockstep with the generated registry vocabulary (SectionState / ProjectionId
parity), validate required fields (subject, tenantId, generatedAt), round-trip
the contract version, and expose a catchable typed error hierarchy rooted at
``ProjectionError``.
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
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_SECTION_STATES,
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionError,
    ProjectionId,
    ProjectionNotFound,
    ProjectionNotImplemented,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    SectionState,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from services.operational_intelligence.models import (  # noqa: E402
    EntityRef,
    EvidenceRef,
    TimeRangeFilter,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _entity_ref(kind: str = "user", ident: str = "usr_1") -> EntityRef:
    return EntityRef(kind=kind, id=ident)


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "profile360",
        "tenantId": "tenant-a",
        "subject": _entity_ref(),
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
                subject=_entity_ref(),
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
# SectionState / ProjectionId parity with the generated registry
# ---------------------------------------------------------------------------

def test_section_state_covers_exactly_the_generated_states() -> None:
    # The 6 section states are generated; SectionState must match exactly.
    assert len(PROJECTION_SECTION_STATES) == 6
    assert set(get_args(SectionState)) == set(PROJECTION_SECTION_STATES)
    assert tuple(get_args(SectionState)) == PROJECTION_SECTION_STATES


def test_projection_id_derived_from_generated_ids() -> None:
    assert tuple(get_args(ProjectionId)) == INTELLIGENCE_PROJECTION_IDS


# ---------------------------------------------------------------------------
# Required-field validation
# ---------------------------------------------------------------------------

def test_request_requires_subject() -> None:
    with pytest.raises(ValidationError):
        ProjectionRequest(projectionId="profile360", tenantId="tenant-a")


def test_request_requires_tenant_id() -> None:
    with pytest.raises(ValidationError):
        ProjectionRequest(projectionId="profile360", subject=_entity_ref())


def test_request_accepts_optional_fields() -> None:
    req = _request(
        timeRange=TimeRangeFilter(
            from_="2026-01-01T00:00:00Z", to="2026-08-01T00:00:00Z"
        ),
        includeSections=["summary", "timeline"],
        includeClaims=True,
    )
    assert req.tenantId == "tenant-a"
    assert req.subject.id == "usr_1"
    assert req.includeSections == ["summary", "timeline"]
    assert req.includeClaims is True
    assert req.timeRange is not None and req.timeRange.to == "2026-08-01T00:00:00Z"


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
        ContractVersionIncompatible("contract version mismatch"),
        DependencyUnavailable("hard dependency unavailable"),
        ProjectionNotImplemented("registered but not implemented"),
    ):
        assert isinstance(exc, ProjectionError)
        assert exc.context == {}
        assert exc.projection_id is None


def test_projection_not_found_is_caught_as_base_error() -> None:
    try:
        raise ProjectionNotFound("boom", projection_id="profile360")
    except ProjectionError as caught:
        assert isinstance(caught, ProjectionNotFound)
        assert caught.projection_id == "profile360"
