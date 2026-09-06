"""Social360 projection-surface adapter — social / relationship / narrative lenses.

social360 is the Relationship360-bound social-evidence intelligence projection
(registry row ``in_flight``). This adapter is the M9 exploration-fabric seam for
its three registered overlay lenses — ``socialfi``, ``engagementfi`` and
``narrative`` — which surface the M1 filter-field categories declared on the
``social360`` exploration-surface row (``social``, ``relationship``,
``incentive``, ``source``, ``evidence``, ``path``, ``narrative``, ``entity``,
``time``).

It mirrors :class:`ProjectionSurfaceAdapter <services.exploration.adapters.projection.ProjectionSurfaceAdapter>`
exactly: it composes the tenant-scoped request, runs the social360 projection
through the fail-isolated A8 engine, and reshapes the engine result into the
exploration ``AdapterResult`` envelope.

Honesty posture (ADR-010; Social360 blueprint invariants):

* **Flag-gated OFF** — ``AETHER_SOCIAL_LENSES_ENABLED`` (read defensively;
  default OFF, and ``config/settings.py`` is never edited here). While the flag
  is off the adapter reports an honest ``feature_disabled`` degraded state
  instead of running.
* **Never fabricates** — the social360 projection row is ``in_flight`` and has
  no registered provider on this branch, so ``execute`` reports
  ``provider_unavailable`` with ``populated=False`` and empty sections rather
  than synthesising followers / engagement / relationship-strength metrics.
* **No-evidence is not zero** — unknown stays unknown; zero is only ever a
  measured value.
* **Read-only** — it only ever runs a projection; it has no write path.

Like the generic :class:`ProjectionSurfaceAdapter`, this class is intentionally
NOT registered in the surface-adapter registry: the social360 product surfaces
are M10 work, and the ``social360`` exploration-surface row enters the generated
twin (``shared/exploration/generated_surfaces.py``) when the integrator
regenerates. Until then ``capabilities`` claims nothing (an empty supported
category set is honest, never an over-claim).
"""

from __future__ import annotations

import os
from typing import Optional

from shared.exploration.generated_surfaces import SURFACE_CAPABILITIES

from services.exploration.adapters.base import AdapterContext, AdapterResult
from services.exploration.adapters.projection import ProjectionSurfaceAdapter

# Rollout flag for the SocialFi / EngagementFi / Narrative lens surfaces.
_SOCIAL_LENSES_FLAG = "AETHER_SOCIAL_LENSES_ENABLED"

# Content-free degraded reason for the flag-off state (distinct from
# ``provider_unavailable``: disabled is a deployment state, not a data state).
_REASON_FEATURE_DISABLED = "feature_disabled"


def social_lenses_enabled() -> bool:
    """Read the ``AETHER_SOCIAL_LENSES_ENABLED`` rollout flag defensively.

    Defaults OFF (fail-closed). The environment is the rollout channel the
    fabric uses for every ``AETHER_*`` feature switch. When the env var is not
    set, we attempt one defensive read of the app settings object and treat any
    missing / malformed setting as OFF; ``config/settings.py`` is sibling-owned
    and is never modified here.
    """
    raw = os.environ.get(_SOCIAL_LENSES_FLAG)
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from config.settings import settings as _app_settings
    except Exception:  # noqa: BLE001 - config may be unavailable mid-edit
        return False
    try:
        social_lenses = getattr(_app_settings, "social_lenses", None)
    except Exception:  # noqa: BLE001
        return False
    if social_lenses is None:
        return False
    return bool(getattr(social_lenses, "enabled", False))


class Social360SurfaceAdapter(ProjectionSurfaceAdapter):
    """social360 exploration surface -> the social360 intelligence projection.

    Subclass declares ``surface_id`` and ``projection_id`` (equal by name, like
    the other 360 projection adapters). ``execute`` is flag-gated first and then
    delegates to the fail-isolated projection path, so every returned state is
    content-free and never fabricated.
    """

    surface_id = "social360"
    projection_id = "social360"

    def __init__(
        self,
        *,
        runtime: Optional[object] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        # ``runtime`` is forwarded to the projection adapter (tests may bind a
        # fresh-registry executor); ``enabled`` is a test-only override that
        # bypasses the rollout-flag read when set.
        super().__init__(runtime=runtime)
        self._enabled_override = enabled

    @property
    def capabilities(self) -> dict:
        """Registered surface capabilities (defensive read of the twin).

        The ``social360`` surface row is canonical in the registry JSON but only
        reaches ``shared/exploration/generated_surfaces.py`` when the integrator
        regenerates. Until then the row is absent from the generated twin and
        NOTHING is claimed — an empty supported-category set is honest, never an
        over-claim. After regeneration this resolves to the declared row.
        """
        return SURFACE_CAPABILITIES.get(
            self.surface_id, {"supported_field_categories": []}
        )

    def is_enabled(self) -> bool:
        """True when the SocialFi/EngagementFi/Narrative lens surfaces are on."""
        if self._enabled_override is not None:
            return self._enabled_override
        return social_lenses_enabled()

    def availability(self) -> dict:
        """Honest runtime availability of the social360 projection plane.

        Mirrors ``ProviderRegistry.availability()`` for this projection: reports
        whether a provider is registered and the registry row's implementation
        state (``in_flight`` today). There is deliberately no ``ready`` key —
        readiness is never inferred.
        """
        from shared.intelligence_projections.registry import projection_registry

        return dict(
            projection_registry.availability().get(self.projection_id, {})
        )

    async def execute(self, ctx: AdapterContext) -> AdapterResult:
        """Run the social360 projection for the tenant scope.

        Flag-gated first: while ``AETHER_SOCIAL_LENSES_ENABLED`` is off the
        adapter reports an honest ``feature_disabled`` degraded state. Once
        enabled it delegates to the fail-isolated projection path, so an
        ``in_flight`` / provider-less projection degrades to
        ``provider_unavailable`` with no fabricated metrics.
        """
        if not self.is_enabled():
            return self._degraded_result(
                self.surface_id, self.resolved_projection_id, _REASON_FEATURE_DISABLED
            )
        return await super().execute(ctx)


__all__ = ["Social360SurfaceAdapter", "social_lenses_enabled"]
