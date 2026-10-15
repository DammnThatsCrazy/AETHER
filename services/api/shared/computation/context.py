"""The immutable ComputationContext — the scope a computation runs under.

Every canonical computation declares, up front and explicitly, *what* it is
computing over: which tenant, which subject/population, which grain and
dimensions, which event-time window and as-of instant, which currency, and which
versions of identity / model / policy / consent it assumed. Nothing is read
implicitly from process globals, the current route, or the wall clock.

Two contexts that describe the same computation share a deterministic
``context_hash()`` — the dedupe/supersession key for results (generalizing
``shared/measurement/context.py::MeasurementContext.context_hash``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ComputationContext(BaseModel):
    """Immutable scope descriptor carried into every computation run."""

    model_config = ConfigDict(frozen=True)

    # Who
    tenant_id: str
    organization_id: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    population_id: Optional[str] = None

    # Slice
    grain: Optional[str] = None
    dimensions: dict[str, Any] = Field(default_factory=dict)

    # Time (event-time first; parsed/validated upstream via shared/temporal)
    event_time_start: Optional[str] = None
    event_time_end: Optional[str] = None
    as_of: Optional[str] = None
    timezone: str = "UTC"
    calendar: str = "gregorian"
    watermark: Optional[str] = None
    partial_window: bool = False

    # Money
    native_currency: Optional[str] = None
    reporting_currency: Optional[str] = None
    valuation_policy: Optional[str] = None

    # Versioned assumptions
    identity_version: Optional[str] = None
    graph_snapshot_id: Optional[str] = None
    campaign_mapping_version: Optional[str] = None
    journey_version: Optional[str] = None
    model_version: Optional[str] = None
    policy_version: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    registry_version: str = "1"

    # Execution provenance (NOT part of the identity hash)
    execution_mode: str = "live"
    replay_id: Optional[str] = None
    correction_id: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None

    # Fields that define *what* was computed (drive the identity hash). Execution
    # provenance (replay/correction/request/trace ids, mode) is deliberately
    # excluded so a replay of the same scope supersedes rather than forks.
    _IDENTITY_FIELDS: tuple[str, ...] = (
        "tenant_id",
        "organization_id",
        "subject_type",
        "subject_id",
        "population_id",
        "grain",
        "dimensions",
        "event_time_start",
        "event_time_end",
        "as_of",
        "timezone",
        "calendar",
        "native_currency",
        "reporting_currency",
        "valuation_policy",
        "identity_version",
        "graph_snapshot_id",
        "campaign_mapping_version",
        "journey_version",
        "model_version",
        "policy_version",
        "consent_snapshot_id",
        "registry_version",
    )

    def identity_payload(self) -> dict[str, Any]:
        """The subset of fields that define computation identity."""
        return {k: getattr(self, k) for k in self._IDENTITY_FIELDS}

    def context_hash(self) -> str:
        """Deterministic 32-hex-char identity of this computation's scope."""
        payload = json.dumps(
            self.identity_payload(), sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


__all__ = ["ComputationContext"]
