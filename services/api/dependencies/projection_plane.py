"""Boot wiring for the Intelligence Projection Plane (the plane-live seam).

The plane's runtime ``projection_registry`` singleton (``shared/intelligence_projections/registry.py``)
is deliberately NEVER mutated by provider modules at import time: each
provider exposes an explicit ``register_provider(registry)`` and
documents that the global registry is wired by the *caller*. This module is
that caller. The app's ``lifespan`` startup (``main.py``) invokes
:func:`register_implemented_projection_providers` so the declared provider set
is live exactly at boot — and nowhere else.

The registered set is explicit and auditable. Fully implemented providers are
listed in :data:`IMPLEMENTED_PROJECTION_IDS`. Concrete but incomplete
providers can also be registered from :data:`IN_FLIGHT_PROVIDER_IDS`, so
surface frames can expose evidence and explicit unknown/degraded states while
the registry continues to report ``in_flight``. Registration never promotes a
projection's implementation state or implies readiness.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: resolves the ``ProviderRegistry`` forward reference below
    # without importing the registry at module import time (the runtime import
    # stays deferred inside the registration function).
    from shared.intelligence_projections.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# The plane's fully implemented projections, in registration order.
IMPLEMENTED_PROJECTION_IDS: tuple[str, ...] = (
    "economic360",
    "outcome360",
    "infrastructure360",
    "temporal360",
    "population360",
    "geographic360",
    "risk360",
    "fraud360",
    "communication360",
)

# Concrete providers that intentionally remain in-flight. They expose bounded
# canonical evidence and explicit gaps; their registration does not claim that
# every contract slot or temporal mode is complete.
IN_FLIGHT_PROVIDER_IDS: tuple[str, ...] = (
    "agent360",
    "execution360",
    "profile360",
    "relationship360",
    "episode360",
    "social360",
    "cluster360",
    "campaign360",
    "source360",
    "connection360",
    "support360",
    "signals360",
    "memory360",
    "commerce360",
    "workflow360",
)

REGISTERED_PROJECTION_IDS: tuple[str, ...] = (
    *IMPLEMENTED_PROJECTION_IDS,
    *IN_FLIGHT_PROVIDER_IDS,
)


def register_implemented_projection_providers(
    registry: "ProviderRegistry | None" = None,
) -> dict[str, str]:
    """Register every declared provider on the plane's runtime registry.

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
    ``registry``. Provider registration is distinct from full implementation:
    inspect ``implementationState`` in the projection contract for that
    distinction.
    """
    if registry is None:
        from shared.intelligence_projections.registry import projection_registry

        registry = projection_registry

    # Deferred imports keep this module (and the app boot that imports it) free
    # of provider-module side effects until the actual registration moment.
    from value.economic.economic360_provider import (
        register_provider as _register_economic360,
    )
    from graph.infrastructure.provider import (
        register_provider as _register_infrastructure360,
    )
    from journeys.measurement.outcome.provider import (
        register_provider as _register_outcome360,
    )
    from graph.temporal360.provider import (
        register_provider as _register_temporal360,
    )
    from identity.population360.provider import (
        register_provider as _register_population360,
    )
    from graph.geographic360.provider import (
        register_provider as _register_geographic360,
    )
    from intelligence.risk360.provider import (
        register_provider as _register_risk360,
    )
    from intelligence.fraud360.provider import (
        register_provider as _register_fraud360,
    )
    from journeys.communication360.provider import (
        register_provider as _register_communication360,
    )
    from actions.agent.agent360_provider import (
        register_provider as _register_agent360,
    )
    from actions.agent.execution360_provider import (
        register_provider as _register_execution360,
    )
    from identity.profile.profile360_provider import (
        register_provider as _register_profile360,
    )
    from identity.relationship_intelligence.relationship360_provider import (
        register_provider as _register_relationship360,
    )
    from journeys.measurement.episodes.provider import (
        register_provider as _register_episode360,
    )
    from services.social360.provider import (
        register_provider as _register_social360,
    )
    from graph.cluster.cluster360_provider import (
        register_provider as _register_cluster360,
    )
    from journeys.campaign.campaign360_provider import (
        register_provider as _register_campaign360,
    )
    from connectors.provider_runtime.source360_provider import (
        register_provider as _register_source360,
    )
    from connectors.provider_runtime.connection360_provider import (
        register_provider as _register_connection360,
    )
    from journeys.support360.provider import register_provider as _register_support360
    from intelligence.signals.signals360_provider import (
        register_provider as _register_signals360,
    )
    from intelligence.semantic_intelligence.memory360_provider import (
        register_provider as _register_memory360,
    )
    from value.commerce.commerce360_provider import (
        register_provider as _register_commerce360,
    )
    from intelligence.workflow.workflow360_provider import (
        register_provider as _register_workflow360,
    )

    for pid, register in (
        ("economic360", _register_economic360),
        ("outcome360", _register_outcome360),
        ("infrastructure360", _register_infrastructure360),
        ("temporal360", _register_temporal360),
        ("population360", _register_population360),
        ("geographic360", _register_geographic360),
        ("risk360", _register_risk360),
        ("fraud360", _register_fraud360),
        ("communication360", _register_communication360),
        ("agent360", _register_agent360),
        ("execution360", _register_execution360),
        ("profile360", _register_profile360),
        ("relationship360", _register_relationship360),
        ("episode360", _register_episode360),
        ("social360", _register_social360),
        ("cluster360", _register_cluster360),
        ("campaign360", _register_campaign360),
        ("source360", _register_source360),
        ("connection360", _register_connection360),
        ("support360", _register_support360),
        ("signals360", _register_signals360),
        ("memory360", _register_memory360),
        ("commerce360", _register_commerce360),
        ("workflow360", _register_workflow360),
    ):
        if registry.get(pid) is None:
            register(registry)

    return dict(registry.sources())


__all__ = [
    "IMPLEMENTED_PROJECTION_IDS",
    "IN_FLIGHT_PROVIDER_IDS",
    "REGISTERED_PROJECTION_IDS",
    "register_implemented_projection_providers",
]
