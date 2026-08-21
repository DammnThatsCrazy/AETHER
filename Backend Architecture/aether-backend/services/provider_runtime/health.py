"""Provider health engine.

Builds a :class:`ProviderHealthReport` from stored connection signals and the
manifest's declared readiness. The report is the typed health envelope the
control plane reads: lifecycle state, manifest readiness, last-sync timestamps,
rate-limit pressure, and an error counter with the last error.

A provider that is not installed is a hard :class:`ProviderNotInstalled` — there
is no honest health report for a plugin we cannot resolve.
"""

from __future__ import annotations

from typing import Any, Optional

from services.provider_runtime.errors import ProviderNotInstalled
from shared.integration_contracts.health import ProviderHealthReport
from shared.logger.logger import get_logger

logger = get_logger("aether.provider_runtime.health")


class HealthEngine:
    """Builds ProviderHealthReport from stored signals + ConnectionState."""

    def __init__(
        self,
        *,
        connections: Any = None,
        registry: Any = None,
    ) -> None:
        self.connections = connections
        self.registry = registry

    # ── Seam defaults (resolved lazily so imports stay decoupled) ──────────

    def _registry(self) -> Any:
        if self.registry is None:
            from services.provider_runtime.registry import registry
            self.registry = registry
        return self.registry

    # ── Report ─────────────────────────────────────────────────────────────

    async def report(self, connection: Any) -> ProviderHealthReport:
        """provider_identity, connection_id, state=connection.state,
        readiness=manifest.readiness (from plugin.manifest()), plus stored
        sync/error signals from the connection record."""
        provider_identity = connection.provider_identity
        plugin = self._registry().get(provider_identity)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {provider_identity} is not installed in the runtime registry"
            )
        manifest = plugin.manifest()

        readiness = None
        try:
            readiness = manifest.readiness  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive; manifest is required
            readiness = None
        if readiness is None:
            raise ProviderNotInstalled(
                f"provider {provider_identity} manifest has no readiness declaration"
            )

        return ProviderHealthReport(
            provider_identity=provider_identity,
            connection_id=connection.connection_id,
            state=connection.state,
            readiness=readiness,
            last_sync_at=getattr(connection, "last_successful_sync_at", None) or None,
            last_webhook_at=getattr(connection, "last_webhook_at", None),
            rate_limit=getattr(connection, "rate_limit", None),
            error_count=int(getattr(connection, "error_count", 0) or 0),
            last_error=getattr(connection, "last_error", None),
        )


__all__ = ["HealthEngine"]
