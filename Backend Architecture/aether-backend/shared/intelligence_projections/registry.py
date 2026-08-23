"""Runtime provider registry for the intelligence projection plane (P0.5).

The registry is the plane's fail-isolated runtime surface. Every ``register``
is gated on two invariants:

* the provider's ``projection_id`` is a real registry id, and
* the provider's ``contract_version`` shares the registry contract's MAJOR
  semver component (tiny local compare — no external semver dependency).

Identity collisions are rejected: a DIFFERENT provider object for an
already-registered id is a hard error (:class:`DuplicateProjection`), while
re-registering the *same* object is an idempotent no-op (mirroring
``services/provider_runtime/registry.py``).

Fail-isolation is the point: :meth:`build_context` NEVER raises for missing /
incompatible / absent dependencies — those are computed states — and
:meth:`project` wraps every provider call so a raising provider yields a
DEGRADED result instead of taking the plane down. The degraded result's
``degradedReasons`` are content-free (exception class name only; generic
``"projection provider failure"`` for non-ProjectionError exceptions) — the
provider's message / diagnostic ``context`` is NEVER surfaced (fail-closed
secret hygiene, mirroring the model-runtime harness pattern).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared.intelligence_projections.contracts import (
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionResult,
)
from shared.intelligence_projections.errors import (
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionError,
    ProjectionNotFound,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    INTELLIGENCE_PROJECTION_DEFINITIONS,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider

logger = logging.getLogger(__name__)


def _same_major(version: Optional[str], registry_version: str) -> bool:
    """True when ``version`` and ``registry_version`` share a semver major.

    Tiny local split-"-"-major compare (no external semver dependency): the
    pre-release/prerelease suffix and minor/patch components are stripped before
    comparing the first dotted segment. A non-string ``version`` is never
    compatible.
    """
    if not isinstance(version, str) or not isinstance(registry_version, str):
        return False
    try:
        major = version.split("-", 1)[0].split(".", 1)[0]
        registry_major = registry_version.split("-", 1)[0].split(".", 1)[0]
    except ValueError:  # pragma: no cover - split on literal separators cannot fail
        return False
    return major == registry_major and major != ""


class ProviderRegistry:
    """Registry of runtime projection providers (fail-isolated)."""

    def __init__(self, registry_data: Optional[dict] = None) -> None:
        self._registry_data = (
            registry_data if registry_data is not None else INTELLIGENCE_PROJECTION_DEFINITIONS
        )
        self._registry_ids: tuple[str, ...] = tuple(self._registry_data)
        self._providers: dict[str, IntelligenceProjectionProvider] = {}
        self._sources: dict[str, str] = {}

    # ── Registration ────────────────────────────────────────────────────────

    def register(
        self,
        provider: IntelligenceProjectionProvider,
        *,
        source: str = "direct",
    ) -> str:
        """Register a projection provider. Returns the projection id.

        Raises:

        * :class:`ProjectionNotFound` when ``provider.projection_id`` is not a
          registered registry id;
        * :class:`ContractVersionIncompatible` when the provider's
          ``contract_version`` does not share the registry contract's major
          semver component;
        * :class:`DuplicateProjection` when a DIFFERENT provider object is
          registered for an already-registered id.

        Re-registering the SAME object is an idempotent no-op returning the id.
        """
        projection_id = getattr(provider, "projection_id", None)
        if projection_id not in self._registry_data:
            raise ProjectionNotFound(
                f"no projection {projection_id!r} in the intelligence "
                "projection registry",
                projection_id=projection_id,
            )

        version = getattr(provider, "contract_version", None)
        if not _same_major(version, INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION):
            raise ContractVersionIncompatible(
                f"provider contract version {version!r} is incompatible with "
                f"registry contract {INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION!r}",
                projection_id=projection_id,
                version=version,
            )

        existing = self._providers.get(projection_id)
        if existing is not None:
            if existing is provider:
                return projection_id
            raise DuplicateProjection(
                f"a provider for {projection_id!r} is already registered",
                projection_id=projection_id,
            )

        self._providers[projection_id] = provider
        self._sources[projection_id] = source
        logger.info(
            "registered projection provider %s (source=%s)", projection_id, source
        )
        return projection_id

    def unregister(self, projection_id: str) -> None:
        """Remove a registered provider. A no-op when the id is absent."""
        self._providers.pop(projection_id, None)
        self._sources.pop(projection_id, None)

    # ── Lookup / introspection ──────────────────────────────────────────────

    def get(self, projection_id: str) -> Optional[IntelligenceProjectionProvider]:
        """Return the provider for ``projection_id``, or ``None`` when absent."""
        return self._providers.get(projection_id)

    def require(self, projection_id: str) -> IntelligenceProjectionProvider:
        """Return the provider for ``projection_id``, raising when absent."""
        provider = self._providers.get(projection_id)
        if provider is None:
            raise ProjectionNotFound(
                f"no provider registered for {projection_id!r}",
                projection_id=projection_id,
            )
        return provider

    def list(self) -> list[IntelligenceProjectionProvider]:
        """All registered providers, in registration order."""
        return list(self._providers.values())

    def sources(self) -> dict[str, str]:
        """Projection id -> registration source (``direct``, ``test``, ...)."""
        return dict(self._sources)

    def supported_contracts(self) -> set[tuple[str, str]]:
        """(projection_id, contract_version) pairs for every registered provider."""
        return {
            (projection_id, getattr(provider, "contract_version", ""))
            for projection_id, provider in self._providers.items()
        }

    def availability(self) -> dict[str, dict]:
        """Pure introspection for EVERY registry id (registered or not).

        Each entry is ``{"registered": bool, "registryState": <definition
        implementationState>, "contractCompatible": bool}``. There is
        deliberately NO ``ready`` key — readiness is never inferred from import
        or registration success; ``contractCompatible`` is NOT readiness.
        """
        availability: dict[str, dict] = {}
        for projection_id in self._registry_ids:
            provider = self._providers.get(projection_id)
            registered = provider is not None
            compatible = registered and _same_major(
                getattr(provider, "contract_version", None),
                INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            )
            availability[projection_id] = {
                "registered": registered,
                "registryState": self._registry_data[projection_id][
                    "implementationState"
                ],
                "contractCompatible": compatible,
            }
        return availability

    def graph_mutation_policy(self, projection_id: str) -> str:
        """The generated definition's ``graphMutationPolicy`` for a projection."""
        if projection_id not in self._registry_data:
            raise ProjectionNotFound(
                f"no projection {projection_id!r} in the intelligence "
                "projection registry",
                projection_id=projection_id,
            )
        return self._registry_data[projection_id]["graphMutationPolicy"]

    # ── Context / execution ─────────────────────────────────────────────────

    async def build_context(
        self,
        projection_id: str,
        request: ProjectionRequest,
    ) -> ProjectionContext:
        """Compute the runtime context for a projection request.

        NEVER raises for missing / incompatible / absent dependencies — those
        are computed states (``missing`` / ``degraded`` / ``not_applicable``).
        Only an unknown projection id raises (:class:`ProjectionNotFound`).
        """
        if projection_id not in self._registry_data:
            raise ProjectionNotFound(
                f"no projection {projection_id!r} in the intelligence "
                "projection registry",
                projection_id=projection_id,
            )

        definition = self._registry_data[projection_id]
        dependency_state: list[ProjectionDependencyState] = []
        warnings: list[str] = []

        for dep in definition.get("projectionDependencies", ()):
            dependency_state.append(
                self._dependency_state(dep, hard=True, warnings=warnings)
            )
        for dep in definition.get("optionalProjectionDependencies", ()):
            dependency_state.append(
                self._dependency_state(dep, hard=False, warnings=warnings)
            )

        return ProjectionContext(
            projectionId=projection_id,
            tenantId=request.tenantId,
            registryState=definition["implementationState"],
            dependencyState=dependency_state,
            warnings=warnings,
        )

    def _dependency_state(
        self,
        dep: str,
        *,
        hard: bool,
        warnings: list[str],
    ) -> ProjectionDependencyState:
        """One sibling-projection dependency's computed state (never raises)."""
        provider = self._providers.get(dep)
        if provider is None:
            state = "missing" if hard else "not_applicable"
            reason = "no provider registered" if hard else "optional dependency not implemented"
            return ProjectionDependencyState(
                projectionId=dep, state=state, reason=reason
            )

        version = getattr(provider, "contract_version", None)
        if not _same_major(version, INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION):
            warnings.append(
                f"dependency {dep!r} provider contract {version!r} is "
                f"incompatible with registry contract "
                f"{INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION!r}"
            )
            return ProjectionDependencyState(
                projectionId=dep,
                state="degraded",
                reason=f"provider contract version {version!r} incompatible",
            )

        return ProjectionDependencyState(projectionId=dep, state="available")

    async def project(
        self,
        projection_id: str,
        request: ProjectionRequest,
    ) -> ProjectionResult:
        """Run one projection, fail-isolating the provider.

        An unregistered id raises :class:`ProjectionNotFound`. Any provider
        failure — a :class:`ProjectionError` subclass or any other exception —
        returns a DEGRADED result with empty sections/claims and content-free
        ``degradedReasons`` (exception class name only / generic fallback). A
        provider's normal result is returned as-is.
        """
        provider = self.require(projection_id)
        context = await self.build_context(projection_id, request)
        try:
            result = await provider.project(request, context)
        except ProjectionError as exc:
            return self._degraded_result(
                projection_id, request, context, [type(exc).__name__]
            )
        except Exception:  # noqa: BLE001 - any provider failure is fail-isolated
            return self._degraded_result(
                projection_id, request, context, ["projection provider failure"]
            )
        return result

    @staticmethod
    def _degraded_result(
        projection_id: str,
        request: ProjectionRequest,
        context: ProjectionContext,
        reasons: list[str],
    ) -> ProjectionResult:
        """A valid DEGRADED result — empty sections/claims, content-free reasons."""
        return ProjectionResult(
            projectionId=projection_id,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=context.dependencyState,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=reasons,
        )


# Module-level singleton shared by the runtime service layer (mirrors
# services/provider_runtime/registry.py).
projection_registry = ProviderRegistry()
registry = projection_registry


__all__ = [
    "ProviderRegistry",
    "projection_registry",
    "registry",
]
