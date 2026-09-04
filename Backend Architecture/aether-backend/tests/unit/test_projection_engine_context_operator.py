"""Context-operator tests (A8): ``G @ C`` — pure functional request transform.

The context operator applies a lens frame / engine temporal mode to a request,
yielding a FRESH request every time. It never mutates the caller's request and
it never widens tenant scope (tenant id is server-authoritative and carried
through untouched).
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

from shared.intelligence_projections.contracts import ProjectionRequest, ProjectionSubject  # noqa: E402
from shared.projection_engine.context_operator import (  # noqa: E402
    ContextOperation,
    ContextOperator,
)
from shared.projection_engine.lens_set import LensSet  # noqa: E402
from shared.projection_engine.temporal_modes import TemporalMode  # noqa: E402


def _request(**overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "outcome360",
        "tenantId": "tenant-a",
        "subject": ProjectionSubject(kind="campaign", id="camp_1"),
        "lensIds": ["standard", "outcome"],
        "temporalMode": "window",
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def test_set_temporal_dispatches_engine_mode_to_surface_mode() -> None:
    result = ContextOperator(ContextOperation.SET_TEMPORAL, {"temporal_mode": "as_of"}).apply(
        _request()
    )
    assert result.temporalMode == "as_of"
    assert result.projectionId == "outcome360"
    assert result.lensIds == ["standard", "outcome"]


def test_set_subject_rebinds_same_kind_new_id() -> None:
    result = ContextOperator(
        ContextOperation.SET_SUBJECT, {"subject_id": "camp_2"}
    ).apply(_request())
    assert result.subject == ProjectionSubject(kind="campaign", id="camp_2")
    assert result.tenantId == "tenant-a"


def test_add_lens_is_idempotent() -> None:
    op = ContextOperator(ContextOperation.ADD_LENS, {"lens_id": "economic"})
    lens_set = LensSet("standard", ("outcome", "economic"))
    first = op.apply(_request(), lens_set=lens_set)
    second = op.apply(first, lens_set=lens_set)
    assert first.lensIds == ["standard", "outcome", "economic"]
    assert first.lensIds == second.lensIds  # no duplicate overlay


def test_remove_lens_drops_only_the_requested_overlay() -> None:
    lens_set = LensSet("standard", ("outcome", "economic"))
    result = ContextOperator(
        ContextOperation.REMOVE_LENS, {"lens_id": "economic"}
    ).apply(_request(), lens_set=lens_set)
    assert result.lensIds == ["standard", "outcome"]
    # Removing an absent overlay is a no-op on the frame.
    noop = ContextOperator(
        ContextOperation.REMOVE_LENS, {"lens_id": "nope"}
    ).apply(_request(), lens_set=lens_set)
    assert noop.lensIds == ["standard", "outcome", "economic"]


def test_set_sections_restricts_rendered_sections() -> None:
    result = ContextOperator(
        ContextOperation.SET_SECTIONS, {"sections": ["summary", "timeline"]}
    ).apply(_request())
    assert result.includeSections == ["summary", "timeline"]


def test_operator_never_mutates_caller_request() -> None:
    original = _request()
    ContextOperator(ContextOperation.SET_TEMPORAL, {"temporal_mode": "compare"}).apply(
        original
    )
    assert original.temporalMode == "window"
    assert original.lensIds == ["standard", "outcome"]


def test_operator_never_widens_tenant_scope() -> None:
    # Even a subject rebind keeps the server-authoritative tenant id.
    result = ContextOperator(
        ContextOperation.SET_SUBJECT, {"subject_id": "camp_2"}
    ).apply(_request())
    assert result.tenantId == "tenant-a"
