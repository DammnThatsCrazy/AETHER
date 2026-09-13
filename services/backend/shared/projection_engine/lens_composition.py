"""Lens composition algebra (A8 projection engine).

The composition laws turn a :class:`LensSet` into a deterministic ordered lens
sequence plus the lenses that cannot compose:

* **Identity** — composing no overlays yields the base lens alone.
* **Idempotence** — a repeated overlay composes once.
* **Order stability** — overlays compose in registry-declared (id-sorted)
  order regardless of request order, so the same set always produces the same
  composition.
* **Disparate grain** — a lens that cannot apply to the requested subject kind
  (its ``applicableSubjectKinds`` excludes it) is a ``CAPABILITY_MISSING``
  conflict and is dropped with a degradation, never silently merged.

Composition never raises for a recoverable conflict — it returns
``(composed, incompatible)`` so the executor can degrade the affected sections.
An ILLEGAL composition (unresolvable id, wrong base, non-base base lens) raises
:class:`LensConflict` (``PARAMETER_CONFLICT``) — those are request bugs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.projection_engine.conflict import (
    ConflictClass,
    ConflictResolution,
    LensConflict,
    LensNotFound,
)
from shared.projection_engine.lens_registry import LensDescriptor, LensRegistry
from shared.projection_engine.lens_set import LensSet


@dataclass(frozen=True)
class Composition:
    """The result of composing a lens set over a subject.

    ``ordered_lens_ids`` — the deterministic base+overlay sequence (composed).
    ``incompatible`` — lenses dropped for a recoverable conflict, each carrying
    its ``ConflictClass`` (``CAPABILITY_MISSING`` today) and a human reason.
    ``resolutions`` — the set of conflict resolutions that were applied.
    """

    ordered_lens_ids: tuple[str, ...]
    incompatible: tuple["IncompatibleLens", ...] = field(default_factory=tuple)
    resolutions: tuple[ConflictResolution, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IncompatibleLens:
    """One lens dropped by a recoverable composition conflict."""

    lens_id: str
    conflict_class: ConflictClass
    reason: str


def _overlay_order(lens_id: str, registry: LensRegistry) -> int:
    """Registry-declared order index for a lens id (stable sort key)."""
    return list(registry.ids()).index(lens_id)


def compose_lenses(
    lens_set: LensSet,
    *,
    subject_kind: Optional[str] = None,
    registry: Optional[LensRegistry] = None,
) -> Composition:
    """Compose a lens set over a subject kind (deterministic).

    Raises :class:`LensConflict` (``PARAMETER_CONFLICT``) for an ILLEGAL
    composition — unresolvable lens id, a base lens composed as an overlay, or
    an overlay whose declared base is not the set's base.
    """
    reg = registry or LensRegistry()
    lens_set.validate(reg)
    descriptors = reg.resolve(lens_set.lens_ids())
    base, overlays = descriptors[0], descriptors[1:]

    # Idempotence + order stability: dedupe, then sort by registry order.
    seen: set[str] = set()
    ordered: list[LensDescriptor] = [base]
    for descriptor in overlays:
        if descriptor.id not in seen:
            seen.add(descriptor.id)
            ordered.append(descriptor)
    ordered_overlays = sorted(ordered[1:], key=lambda d: _overlay_order(d.id, reg))
    composed = [base, *ordered_overlays]

    incompatible: list[IncompatibleLens] = []
    resolutions: set[ConflictResolution] = set()
    if subject_kind is not None:
        applicable: list[LensDescriptor] = [composed[0]]
        for descriptor in composed[1:]:
            if subject_kind not in descriptor.applicable_subject_kinds:
                incompatible.append(
                    IncompatibleLens(
                        lens_id=descriptor.id,
                        conflict_class=ConflictClass.CAPABILITY_MISSING,
                        reason=(
                            f"lens {descriptor.id!r} cannot apply to subject kind "
                            f"{subject_kind!r} (its applicableSubjectKinds exclude it)"
                        ),
                    )
                )
                resolutions.add(ConflictResolution.DEGRADE)
            else:
                applicable.append(descriptor)
        composed = applicable

    return Composition(
        ordered_lens_ids=tuple(d.id for d in composed),
        incompatible=tuple(incompatible),
        resolutions=tuple(sorted(resolutions, key=lambda r: r.value)),
    )


__all__ = ["Composition", "IncompatibleLens", "compose_lenses"]
