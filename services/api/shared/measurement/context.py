"""Measurement context — the deterministic identity of *what* was measured.

A :class:`MeasurementContext` names the tenant, the time window, and the
measurement conventions (timezone, attribution model, registry version) under
which a metric is computed. Its :meth:`context_hash` is a stable fingerprint:
two results computed under an identical context share a hash, so a persistence
layer can dedupe, supersede, and restate results without re-deriving intent.

The model is frozen: once a context exists its hash can never drift.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict


class MeasurementContext(BaseModel):
    """Immutable description of the conditions under which a metric is measured."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    window_start: str
    window_end: str
    timezone: str = "UTC"
    attribution_model: str = "last_touch"
    registry_version: str = "1"

    def context_hash(self) -> str:
        """Deterministic sha256 (first 32 hex chars) over the six context fields.

        Canonicalised as sorted-key, whitespace-free JSON so the same context
        always yields the same hash, regardless of field construction order.
        """

        payload = {
            "tenant_id": self.tenant_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "timezone": self.timezone,
            "attribution_model": self.attribution_model,
            "registry_version": self.registry_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
