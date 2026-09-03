"""Boot wiring for the Intelligence Projection Plane (the plane-live seam).

The plane's runtime ``projection_registry`` singleton (``shared/intelligence_projections/registry.py``)
is deliberately NEVER mutated by provider modules at import time: each
implemented provider exposes an explicit ``register_provider(registry)`` and
documents that the global registry is wired by the *caller*. This module is
that caller. The app's ``lifespan`` startup (``main.py``) invokes
:func:`register_implemented_projection_providers` so the plane's implemented
providers are live exactly at boot — and nowhere else.

The registered set is explicit and auditable: every projection whose registry
row is ``implementationState: "implemented"`` belongs in
:data:`IMPLEMENTED_PROJECTION_IDS`, and its provider module is added below in
the SAME change that flips the row. A provider that is implemented but not
listed here is not live (the phase-1 enforcement note in
``docs/source-of-truth/INTELLIGENCE_PROJECTION_ARCHITECTURE.md``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The plane's implemented projections, in registration order. When a follow-up
# vertical slice flips a row to ``implemented`` (e.g. risk360 / fraud360 /
# geographic360 / population360), add its provider module below and extend this
# tuple in the same change.
IMPLEMENTED_PROJECTION_IDS: tuple[str, ...] = (
    "economic360",
    "outcome360",
    "infrastructure360",
    "temporal360",
)


def register_implemented_projection_providers(
    registry: "ProviderRegistry | None" = None,
) -> dict[str, str]:
    """Register every implemented projection provider on the plane's registry.

    Defaults to the global ``projection_registry`` singleton (the app-boot call
    site); tests pass a fresh :class:`ProviderRegistry` to avoid touching the
    global. Imports are deferred so importing this module never imports the
    provider services and never mutates the global — registration happens only
    when the function runs.

    Idempotent across repeated boot calls: each provider module constructs a
    fresh instance per ``register_provider`` call, so the registry's same-object
    idempotency does not make a second boot safe on its own. This helper guards
    by id — an id already registered is left untouched (never raises, never
    replaces an existing provider), so a repeated lifespan entry in one process
    registers exactly once.

    Returns ``{projection_id: source}`` for everything registered on
    ``registry``.
    """
    if registry is None:
        from shared.intelligence_projections.registry import projection_registry

        registry = projection_registry

    # Deferred imports keep this module (and the app boot that imports it) free
    # of provider-module side effects until the actual registration moment.
    from services.economic.economic360_provider import (
        register_provider as _register_economic360,
    )
    from services.infrastructure.provider import (
        register_provider as _register_infrastructure360,
    )
    from services.measurement.outcome.provider import (
        register_provider as _register_outcome360,
    )
    from services.temporal360.provider import (
        register_provider as _register_temporal360,
    )

    for pid, register in (
        ("economic360", _register_economic360),
        ("outcome360", _register_outcome360),
        ("infrastructure360", _register_infrastructure360),
        ("temporal360", _register_temporal360),
    ):
        if registry.get(pid) is None:
            register(registry)

    return dict(registry.sources())


__all__ = [
    "IMPLEMENTED_PROJECTION_IDS",
    "register_implemented_projection_providers",
]
