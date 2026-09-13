"""Derivatives Intelligence foundation helpers — re-exports of the shared
route-correctness helpers plus domain utilities. Observation-only invariant:
execution_by_aether=False everywhere; read-only credential authority only."""

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
    "require_read_only_authority",
]


def require_flag(flag: bool, name: str) -> None:
    """Fail-closed feature gate: disabled surfaces look like they don't exist."""
    if not flag:
        raise HTTPException(status_code=404, detail=f"{name} is not enabled")


def require_read_only_authority(authority_type: str) -> None:
    """Aether never accepts trade or withdrawal credential scopes."""
    if authority_type != "read_only":
        raise ValueError(
            f"credential authority {authority_type!r} refused — Aether only "
            "accepts read_only venue credentials (no trade/withdraw scopes)"
        )


def deterministic_id(prefix: str, basis: str) -> str:
    return prefix + hashlib.sha256(basis.encode()).hexdigest()[:32]


def deterministic_idempotency_key(basis: str) -> str:
    return hashlib.sha256(basis.encode()).hexdigest()


def make_event(event_name: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Canonical-event dict returned to callers — never wired to the bus here."""
    return {
        "event_name": event_name,
        "tenant_id": tenant_id,
        "payload": dict(payload),
        "occurred_at": utc_now_iso(),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
