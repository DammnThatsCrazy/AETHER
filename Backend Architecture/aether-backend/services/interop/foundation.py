"""Interoperability Intelligence foundation helpers — re-exports of the
shared route-correctness helpers plus domain utilities. Public-scope rows
use the sentinel tenant 'public'."""

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

PUBLIC_TENANT = "public"

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
    "PUBLIC_TENANT",
]


def require_flag(flag: bool, name: str) -> None:
    """Fail-closed feature gate: disabled surfaces look like they don't exist."""
    if not flag:
        raise HTTPException(status_code=404, detail=f"{name} is not enabled")


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
