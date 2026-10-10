"""Notification Intelligence — Audit Trail Helpers

Append-only audit entries. The audit_trail field is JSONB and never mutated —
only entries are appended.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_audit_entry(
    state: str,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "state": state,
        "timestamp": _utc_now(),
        "actor": {
            "user_id": actor_user_id or "system",
            "role": actor_role or "system",
        },
    }
    if metadata:
        entry["metadata"] = metadata
    return entry
