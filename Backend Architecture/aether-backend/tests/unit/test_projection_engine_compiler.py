"""Projection-engine compiler tests (A8): compile → IR, operators, temporal fit.

Compilation is the fail-fast stage: an illegal composition, an illegal operator
request, or a lens set that cannot honor the requested temporal mode is
surfaced here as a typed ``LensConflict`` before any provider runs. Recoverable
conflicts (a lens that does not support the requested temporal mode) degrade
the lens rather than fail the request.
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

from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionRequest,
    ProjectionSubject,
)
from shared.projection_engine.compiler import ProjectionCompiler  # noqa: E402
from shared.projection_engine.conflict import ConflictClass, LensConflict  # noqa: E402
from shared.projection_engine.lens_set import LensSet  # noqa: E402
from shared.projection_engine.operators import Operator, OperatorSpec  # noqa: E402
from shared.projection_engine.temporal_modes import TemporalMode  # noqa: E402


def _request(
    projection_id: str = "outcome360",
    kind: str = "campaign",
    **overrides: object,
) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": projection_id,
        "tenantId": "tenant-a",
        "subject": ProjectionSubject(kind=kind, id="camp_1"),
        "lensIds": ["economic"],
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def test_compile_minimal() -> None:
    ir = ProjectionCompiler().compile(_request())
    assert ir.projection_id == "outcome360"
    assert ir.lens_ids == ("standard", "economic")  # non-base lens -> overlay on standard
    assert ir.temporal_mode is TemporalMode.LIVE
    assert ir.incompatible_lenses == ()


def test_compile_preserves_request_passthrough() -> None:
    ir = ProjectionCompiler().compile(
        _request(includeSections=["summary"], includeClaims=True)
    )
    assert ir.requested_sections == ("summary",)
    assert ir.requested_claims is True
    assert ir.tenant_id == "tenant-a"


def test_compile_temporal_drop_for_unsupported_lens() -> None:
    """A lens that cannot honor the mode is dropped (TEMPORAL_CONFLICT → DEGRADE),
    and the remaining lens still compiles."""
    ir = ProjectionCompiler().compile(
        _request(lensIds=["consent", "economic"]),
        temporal_mode=TemporalMode.SIMULATION,
    )
    # consent supports window/as_of/compare — simulation dispatches to relative
    # (unsupported) so consent is dropped; economic supports relative and stays.
    assert "consent" not in ir.lens_ids
    assert "economic" in ir.lens_ids
    dropped = [l.lens_id for l in ir.incompatible_lenses]
    assert "consent" in dropped


def test_compile_no_lens_supports_mode_raises() -> None:
    """When every composed lens cannot honor the mode, compilation fails closed.

    The real day-1 registry's base lens (``standard``) supports all four surface
    modes, so this case is exercised on a custom registry whose base and overlay
    only support ``window``. A lens set whose base alone cannot honor the mode
    raises TEMPORAL_CONFLICT at compile time.
    """
    from shared.projection_engine.lens_registry import LensRegistry

    defs = {
        "base_w": {
            "id": "base_w", "displayName": "Base W", "kind": "base", "baseLens": None,
            "description": "", "domain": "test", "applicableSubjectKinds": ["campaign"],
            "temporalModes": ["window"], "default": True,
        },
        "overlay_w": {
            "id": "overlay_w", "displayName": "Overlay W", "kind": "overlay",
            "baseLens": "base_w", "description": "", "domain": "test",
            "applicableSubjectKinds": ["campaign"], "temporalModes": ["window"],
            "default": False,
        },
    }
    reg = LensRegistry(defs)
    with pytest.raises(LensConflict) as excinfo:
        ProjectionCompiler(lens_registry=reg).compile(
            _request(lensIds=["overlay_w"]),
            temporal_mode=TemporalMode.SIMULATION,  # -> relative, unsupported by all
        )
    assert excinfo.value.conflict_class is ConflictClass.TEMPORAL_CONFLICT


def test_compile_illegal_operator_rejected() -> None:
    """TRAVERSE is illegal on a measurement_360 projection (request bug)."""
    with pytest.raises(LensConflict) as excinfo:
        ProjectionCompiler().compile(
            _request(),
            operators=[OperatorSpec(operator=Operator.TRAVERSE, field="graph")],
        )
    assert excinfo.value.conflict_class is ConflictClass.PARAMETER_CONFLICT


def test_compile_legal_operators_pass() -> None:
    ir = ProjectionCompiler().compile(
        _request(projection_id="profile360"),
        operators=[OperatorSpec(operator=Operator.SELECT, field="summary")],
    )
    assert len(ir.operators) == 1
    assert ir.operators[0].operator is Operator.SELECT


def test_temporal_mode_dispatch_contract() -> None:
    """Engine modes dispatch onto the four registry surface modes only."""
    from shared.projection_engine.temporal_modes import dispatch_temporal_mode

    assert dispatch_temporal_mode(TemporalMode.LIVE) == "window"
    assert dispatch_temporal_mode(TemporalMode.AS_OF) == "as_of"
    assert dispatch_temporal_mode(TemporalMode.KNOWN_THEN) == "as_of"
    assert dispatch_temporal_mode(TemporalMode.KNOWN_NOW) == "as_of"
    assert dispatch_temporal_mode(TemporalMode.COMPARE) == "compare"
    assert dispatch_temporal_mode(TemporalMode.CORRECTION_DIFF) == "compare"
    assert dispatch_temporal_mode(TemporalMode.PLAYBACK) == "relative"
    assert dispatch_temporal_mode(TemporalMode.SIMULATION) == "relative"
