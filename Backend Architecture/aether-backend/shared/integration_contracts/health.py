"""Provider health report for the runtime control plane.

:class:`ProviderHealthReport` is the single typed health envelope a provider
plugin produces: the lifecycle state of a specific connection, its manifest
readiness, the most recent sync/webhook timestamps, rate-limit pressure, and an
error counter with the last error. It reuses the canonical
:class:`~shared.integration_contracts.lifecycle.ConnectionState`,
:class:`~shared.integration_contracts.manifest.ManifestReadiness`, and
:class:`~shared.integration_contracts.results.RateLimitInfo` types — no
re-definition.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import ManifestReadiness
from shared.integration_contracts.results import RateLimitInfo


class ProviderHealthReport(BaseModel):
    """Health snapshot for one tenant<->provider connection."""

    model_config = ConfigDict(extra="forbid")

    provider_identity: str
    connection_id: str
    state: ConnectionState
    readiness: ManifestReadiness
    last_sync_at: Optional[str] = None
    last_webhook_at: Optional[str] = None
    rate_limit: Optional[RateLimitInfo] = None
    error_count: int = 0
    last_error: Optional[str] = None
    schema_version: str = "1"


__all__ = [
    "ProviderHealthReport",
]
