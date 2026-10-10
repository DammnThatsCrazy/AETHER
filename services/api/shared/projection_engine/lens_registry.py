"""Lens registry (A8 projection engine).

A lens is a composable viewing frame a projection applies over canonical Aether
truth. The canonical lens definitions live in the generated twin
(``shared/projection_engine/generated_lenses.py``, itself generated from
``packages/shared/contracts/lens-registry.json``) so the typed vocabulary can
never drift from the JSON.

This module owns the runtime side: :class:`LensDescriptor` (a validated view of
one definition) and :class:`LensRegistry` (register / get / list / resolve a
lens set). The module-level ``lens_registry`` singleton mirrors the
``projection_registry`` singleton of the P0 plane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from shared.projection_engine.conflict import ConflictClass, LensConflict, LensNotFound

# Generated lens definitions — never hand-maintained here (derived from the
# canonical registry JSON by scripts/generate_platform_contracts.py).
from shared.projection_engine.generated_lenses import LENS_DEFINITIONS  # noqa: E402


@dataclass(frozen=True)
class LensDescriptor:
    """A validated, immutable lens definition."""

    id: str
    display_name: str
    kind: str  # "base" | "overlay" (LENS_KINDS vocab)
    base_lens: Optional[str]
    description: str
    domain: str
    applicable_subject_kinds: tuple[str, ...]
    temporal_modes: tuple[str, ...]
    default: bool

    @classmethod
    def from_dict(cls, data: dict) -> "LensDescriptor":
        return cls(
            id=data["id"],
            display_name=data["displayName"],
            kind=data["kind"],
            base_lens=data["baseLens"],
            description=data["description"],
            domain=data["domain"],
            applicable_subject_kinds=tuple(data["applicableSubjectKinds"]),
            temporal_modes=tuple(data["temporalModes"]),
            default=data["default"],
        )

    @property
    def is_base(self) -> bool:
        return self.kind == "base"


class LensRegistry:
    """Registry of projection-engine lenses (fail-closed lookup)."""

    def __init__(self, definitions: Optional[dict] = None) -> None:
        self._definitions = dict(definitions) if definitions is not None else LENS_DEFINITIONS
        self._descriptors: dict[str, LensDescriptor] = {
            lid: LensDescriptor.from_dict(data) for lid, data in self._definitions.items()
        }

    # ── Lookup / introspection ──────────────────────────────────────────────

    def get(self, lens_id: str) -> LensDescriptor:
        """Return the descriptor for ``lens_id``, raising when absent."""
        descriptor = self._descriptors.get(lens_id)
        if descriptor is None:
            raise LensNotFound(lens_id)
        return descriptor

    def has(self, lens_id: str) -> bool:
        return lens_id in self._descriptors

    def list(self) -> list[LensDescriptor]:
        """All lens descriptors, sorted by lens id (deterministic)."""
        return [self._descriptors[lid] for lid in sorted(self._descriptors)]

    def ids(self) -> tuple[str, ...]:
        """Every lens id in THIS registry, sorted (deterministic).

        Derived from the registry's own descriptors (not a module constant) so
        a custom registry — used by composition tests and future extension —
        reports its own ids. For the generated singleton this equals the
        generated ``LENS_IDS``.
        """
        return tuple(sorted(self._descriptors))

    def default_base(self) -> str:
        """The id of the default base lens (exactly one exists)."""
        for descriptor in self._descriptors.values():
            if descriptor.default:
                return descriptor.id
        raise LensConflict(
            "no default base lens declared in the lens registry",
            ConflictClass.PARAMETER_CONFLICT,
        )

    # ── Lens-set resolution ─────────────────────────────────────────────────

    def resolve(self, lens_ids: Iterable[str]) -> list[LensDescriptor]:
        """Resolve every lens id, raising :class:`LensNotFound` on any miss."""
        return [self.get(lid) for lid in lens_ids]

    def validate_lens_set(self, lens_ids: Iterable[str]) -> None:
        """Validate a lens set WITHOUT composing it.

        Raises :class:`LensConflict` (``PARAMETER_CONFLICT``) for:
        * an unresolvable lens id;
        * an overlay whose declared ``baseLens`` is not the set's base lens;
        * a base lens appearing anywhere but the first position.
        """
        ids = list(lens_ids)
        if not ids:
            raise LensConflict(
                "a lens set must name at least a base lens",
                ConflictClass.PARAMETER_CONFLICT,
            )
        descriptors = self.resolve(ids)
        base, overlays = descriptors[0], descriptors[1:]
        if base.kind != "base":
            raise LensConflict(
                f"lens set base {base.id!r} is not a base-kind lens",
                ConflictClass.PARAMETER_CONFLICT,
                lens_id=base.id,
            )
        for overlay in overlays:
            if overlay.kind == "base":
                raise LensConflict(
                    f"base lens {overlay.id!r} must not be composed as an overlay",
                    ConflictClass.PARAMETER_CONFLICT,
                    lens_id=overlay.id,
                )
            if overlay.base_lens != base.id:
                raise LensConflict(
                    f"overlay lens {overlay.id!r} bases on {overlay.base_lens!r}, "
                    f"not the lens set base {base.id!r}",
                    ConflictClass.PARAMETER_CONFLICT,
                    lens_id=overlay.id,
                )


# Module-level singleton shared by the engine (mirrors
# shared/intelligence_projections/registry.py::projection_registry).
lens_registry = LensRegistry()


__all__ = ["LensDescriptor", "LensRegistry", "lens_registry"]
