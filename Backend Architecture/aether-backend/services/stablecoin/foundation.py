"""Stablecoin Intelligence foundation helpers.

Re-exports the agentic observability route-correctness helpers (tenant
context, permission checks, execution-refusal, graph persistence) and adds
the small deterministic-identity and feature-flag helpers shared by every
stablecoin module.

INVARIANT: this domain observes and verifies externally-executed stablecoin
activity. It never originates, signs, or settles transfers. Every
tenant-scoped record carries execution_by_aether=False.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from services.agentic_observability.foundation import (  # noqa: F401
    GraphProjectionResult,
    active_tenant_id,
    check_no_execution,
    normalize_graph_tenant_properties,
    persist_mutations,
    require_permission,
    validate_event_name,
    validate_payload_tenant,
)

__all__ = [
    "GraphProjectionResult",
    "active_tenant_id",
    "check_no_execution",
    "normalize_graph_tenant_properties",
    "persist_mutations",
    "require_permission",
    "validate_event_name",
    "validate_payload_tenant",
    "require_flag",
    "deterministic_id",
    "deterministic_idempotency_key",
    "make_event",
    "utc_now_iso",
]


def require_flag(flag: bool, name: str) -> None:
    """Fail-closed feature gate: disabled surfaces look like they don't exist."""
    if not flag:
        raise HTTPException(status_code=404, detail=f"{name} is not enabled")


def deterministic_id(prefix: str, basis: str) -> str:
    """Stable record id: prefix + first 32 hex chars of sha256(basis)."""
    return prefix + hashlib.sha256(basis.encode()).hexdigest()[:32]


def deterministic_idempotency_key(basis: str) -> str:
    """Full sha256 hex digest of the same basis used for the record id."""
    return hashlib.sha256(basis.encode()).hexdigest()


def make_event(event_name: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a canonical-event dict for the caller to publish.

    The stablecoin services return these in ``emitted_events`` lists —
    they do NOT wire the event bus themselves.
    """
    return {
        "event_name": event_name,
        "tenant_id": tenant_id,
        "payload": dict(payload),
        "occurred_at": utc_now_iso(),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
