"""Base projector contract — all Silver projectors implement this interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectionResult:
    """Result of projecting a single Bronze event into Silver facts."""
    table: str
    rows: list[dict[str, Any]]
    skipped: bool = False
    skip_reason: str | None = None


class BaseProjector:
    """
    Projects a Bronze event dict into one or more Silver fact rows.

    Subclasses override `handles` (set of event types) and `project`.

    Projectors MUST be idempotent: the same source_event_id written twice
    must be a no-op at the database level (UNIQUE constraint on idempotency_key
    or ON CONFLICT DO NOTHING based on source_event_id).
    """

    handles: frozenset[str] = frozenset()

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _base_row(self, event: dict[str, Any]) -> dict[str, Any]:
        ctx = event.get("context") or {}
        return {
            "source_event_id": event.get("messageId"),
            "source_event_type": event.get("type"),
            "tenant_id": (ctx.get("tenantId") or event.get("tenantId") or "default"),
            "actor_id": ctx.get("actorId"),
            "user_id": event.get("userId"),
            "anonymous_id": event.get("anonymousId"),
            "org_id": ctx.get("orgId"),
            "occurred_at": event.get("timestamp"),
            "consent_snapshot_id": ctx.get("consentSnapshotId"),
            "privacy_class": self._privacy_class(event),
            "idempotency_key": event.get("messageId"),
            "payload": event.get("properties") or {},
        }

    @staticmethod
    def _privacy_class(event: dict[str, Any]) -> str:
        family = event.get("family", "")
        if family in ("credit", "location"):
            return "sensitive"
        if family in ("identity_lc", "b2b"):
            return "behavioral_pii"
        if family in ("ecommerce", "web3", "web3_lc", "x402"):
            return "financial"
        return "behavioral"

    @staticmethod
    def _props(event: dict[str, Any]) -> dict[str, Any]:
        return event.get("properties") or {}
