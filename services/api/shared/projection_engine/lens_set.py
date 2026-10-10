"""Lens set (A8 projection engine).

A :class:`LensSet` is the immutable request-time artifact that names one base
lens and zero or more overlays to compose over a projection. ``LensSet`` is
carried through compilation and planning so every downstream stage sees the
same, validated lens frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.projection_engine.lens_registry import LensRegistry


@dataclass(frozen=True)
class LensSet:
    """One base lens plus zero or more overlays to compose.

    ``base_lens`` names the base lens id (e.g. ``"standard"``); ``overlays``
    names the overlay lens ids. The overlays' declared ``baseLens`` MUST equal
    ``base_lens`` (validated by :meth:`validate`).
    """

    base_lens: str
    overlays: tuple[str, ...] = ()

    @classmethod
    def from_request(
        cls,
        lens_ids: Optional[list[str]],
        *,
        registry: Optional[LensRegistry] = None,
    ) -> "LensSet":
        """Build a lens set from a request's ``lensIds``.

        Rules:
        * ``None`` / empty → the registry's default base lens alone (identity).
        * First element is the base lens when it IS a base-kind lens; otherwise
          the default base lens is used and every provided id becomes an overlay
          (composing any overlay onto the default base is legal).
        """
        reg = registry or LensRegistry()
        if not lens_ids:
            return cls(base_lens=reg.default_base(), overlays=())
        first = reg.get(lens_ids[0])
        if first.kind == "base":
            return cls(base_lens=first.id, overlays=tuple(lens_ids[1:]))
        return cls(base_lens=reg.default_base(), overlays=tuple(lens_ids))

    def lens_ids(self) -> tuple[str, ...]:
        """The ordered lens id tuple ``(base_lens, *overlays)``."""
        return (self.base_lens, *self.overlays)

    def validate(self, registry: Optional[LensRegistry] = None) -> None:
        """Validate the set against the lens registry (raises ``LensConflict``)."""
        reg = registry or LensRegistry()
        reg.validate_lens_set(self.lens_ids())

    def __str__(self) -> str:  # pragma: no cover - debug convenience
        return "+".join(self.lens_ids())


__all__ = ["LensSet"]
