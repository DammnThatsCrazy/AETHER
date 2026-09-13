"""The single exploration → projection subject join (context-360 Phase 1).

The exploration fabric derives the tenant-scoped ``ProjectionSubject`` a 360
projection is asked about from the context's ``selection.focused`` anchor. That
conversion used to be hand-written in two places — the projection-surface
adapter (``services/exploration/adapters/projection.py``) and the fabric's
session composition (``services/exploration/service.py::_compose_projection``) —
each with a private copy of the same constants. This module is the ONE surface
that owns the mapping, so the adapter data path and the session projection
summary can never disagree about the subject.

Do-not-duplicate boundaries: an ``ExplorationAnchor`` becomes a
``ProjectionSubject`` here and only here. Seams that legitimately speak a
different subject spelling translate *at their own edge* and are deliberately
NOT folded in — they are separate planes, not duplicated shapes of this one:

* ``ComputationContext.subject_type``/``subject_id`` (``shared/computation``) —
  the frozen computation-plane scope model; its subject vocabulary is the
  computation plane's own.
* ``subject_kind``/``subject_id`` REST/read-seam parameters (``/v1/infrastructure/...``
  path params, the Noesis ``projection_read`` kwargs) — public boundary names
  that construct the canonical ``ProjectionSubject`` immediately on entry.
"""

from __future__ import annotations

from shared.exploration.models import ExplorationContextV1
from shared.intelligence_projections.contracts import ProjectionSubject
from shared.intelligence_projections.generated_registry import (
    PROJECTION_SUBJECT_KINDS,
)

_VALID_SUBJECT_KINDS = frozenset(PROJECTION_SUBJECT_KINDS)
_DEFAULT_SUBJECT_KIND = "entity"
_DEFAULT_SUBJECT_ID = "current"


def projection_subject_for(context: ExplorationContextV1) -> ProjectionSubject:
    """The tenant-scoped projection subject for an exploration context.

    A ``selection.focused`` anchor whose kind is a registered projection subject
    kind becomes the subject; otherwise the projection falls back to the
    canonical default (``entity`` / ``current``). One conversion point shared by
    the surface data path and the session-composition summary.
    """
    focus = context.selection.focused if context.selection else None
    if focus is not None and focus.kind in _VALID_SUBJECT_KINDS:
        return ProjectionSubject(kind=focus.kind, id=focus.id)
    return ProjectionSubject(kind=_DEFAULT_SUBJECT_KIND, id=_DEFAULT_SUBJECT_ID)


__all__ = ["projection_subject_for"]
