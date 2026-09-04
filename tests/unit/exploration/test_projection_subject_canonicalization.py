"""Phase-1 SubjectRef canonicalization (context-360 program) — one join surface.

The exploration fabric derives the tenant-scoped ``ProjectionSubject`` a 360
projection is asked about in ONE place —
``services.exploration.projection_subject.projection_subject_for``. Both the
projection-surface adapter data path and the fabric's session composition
(``services.exploration.service::_compose_projection``) go through that single
helper: no second ``focus → ProjectionSubject`` copy and no ad-hoc
``subject_type``/``subject_id`` shape on the projection plane.

The do-not-duplicate boundary is deliberate: ``ComputationContext.subject_type``
(computation plane), the ``/v1/infrastructure/{subject_kind}/{subject_id}`` REST
path params and the Noesis ``projection_read`` kwargs are separate planes /
public seam names that construct the canonical subject on entry — they are NOT
duplicated shapes of this one and are untouched.
"""

from __future__ import annotations

from shared.exploration.models import (
    ExplorationAnchor,
    ExplorationContextV1,
    ExplorationScope,
    SelectionSet,
    TemporalSelection,
)
from shared.intelligence_projections.contracts import ProjectionSubject
from shared.intelligence_projections.generated_registry import (
    PROJECTION_SUBJECT_KINDS,
)

from services.exploration.projection_subject import projection_subject_for


def _context(*, focus: ExplorationAnchor | None = None) -> ExplorationContextV1:
    return ExplorationContextV1(
        scope=ExplorationScope(tenant_id="tenant-a", surface="economic360"),
        temporal=TemporalSelection(mode="window", field="occurred_at", timezone="UTC"),
        selection=SelectionSet(focused=focus) if focus is not None else None,
    )


def _registered_non_default_kind() -> str:
    """A projection subject kind that is not the default (``entity``)."""
    for kind in PROJECTION_SUBJECT_KINDS:
        if kind != "entity":
            return kind
    raise AssertionError("registry declares only the default subject kind")


class TestProjectionSubjectFor:
    async def test_focused_anchor_maps_to_canonical_subject(self) -> None:
        kind = _registered_non_default_kind()
        subject = projection_subject_for(_context(focus=ExplorationAnchor(kind=kind, id="sub-42")))
        assert isinstance(subject, ProjectionSubject)
        assert subject.kind == kind
        assert subject.id == "sub-42"

    async def test_no_selection_falls_back_to_default(self) -> None:
        subject = projection_subject_for(_context(focus=None))
        assert subject.kind == "entity"
        assert subject.id == "current"

    async def test_focused_anchor_with_unregistered_kind_falls_back_to_default(
        self,
    ) -> None:
        # A kind outside the generated projection-subject vocabulary never
        # reaches ProjectionSubject construction (extra="forbid" would reject
        # it) — it falls back to the canonical default instead.
        subject = projection_subject_for(
            _context(focus=ExplorationAnchor(kind="not_a_subject_kind", id="x"))
        )
        assert subject.kind == "entity"
        assert subject.id == "current"


class TestSingleConversionSurface:
    """The consolidation pin: both consumers share ONE helper, no local copy."""

    async def test_surface_adapter_and_session_composition_reference_same_helper(
        self,
    ) -> None:
        from services.exploration import service as svc
        from services.exploration.adapters import projection as projection_adapter

        # Both the surface data path and the fabric's session composition bind
        # to the exact same function object.
        assert projection_adapter.projection_subject_for is projection_subject_for
        assert svc.projection_subject_for is projection_subject_for

    async def test_no_duplicate_conversion_surfaces_remain(self) -> None:
        from services.exploration import service as svc
        from services.exploration.adapters import projection as projection_adapter

        # The old private conversion sites are gone — each module now imports
        # the shared helper instead of re-declaring the mapping.
        assert not hasattr(projection_adapter, "_subject_from_context")
        assert not hasattr(svc, "_VALID_SUBJECT_KINDS")
        assert not hasattr(svc, "_DEFAULT_SUBJECT_KIND")
        assert not hasattr(projection_adapter, "_VALID_SUBJECT_KINDS")

    async def test_shared_helper_only_defines_canonical_kind_id(self) -> None:
        # The helper emits the canonical shape; a projection-plane object never
        # carries a subject_type/subject_id spelling (extra="forbid").
        subject = projection_subject_for(_context(focus=None))
        dumped = subject.model_dump()
        assert set(dumped) == {"kind", "id"}
        assert "subject_type" not in dumped
        assert "subject_id" not in dumped
