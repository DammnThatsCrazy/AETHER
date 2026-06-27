"""Base projector contract — all Silver projectors implement this interface."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("aether.silver.base_projector")


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

    After a successful projection, the base class calls _emit_to_canonical_activity()
    which adapts each silver row and upserts it into canonical_activity. This
    keeps the canonical ledger in sync without requiring projector subclasses to
    know about the activity table.
    """

    handles: frozenset[str] = frozenset()

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        raise NotImplementedError

    def project_and_emit(self, event: dict[str, Any]) -> ProjectionResult | None:
        """Project the event then emit canonical activity records.

        Synchronous callers (dispatcher) use this wrapper. Async callers
        can await emit_canonical_activity() directly after calling project().
        """
        result = self.project(event)
        if result and not result.skipped and result.rows:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._emit_to_canonical_activity(result.table, result.rows))
                else:
                    loop.run_until_complete(self._emit_to_canonical_activity(result.table, result.rows))
            except Exception:
                logger.debug(
                    "canonical_activity emit skipped for table=%s (no event loop or activity repo unavailable)",
                    result.table,
                )
        return result

    async def _emit_to_canonical_activity(
        self, silver_table: str, rows: list[dict[str, Any]]
    ) -> None:
        """Adapt silver rows and upsert into canonical_activity."""
        try:
            from services.measurement.silver_adapters import adapt_from_silver
            from services.measurement.repositories.activity_repo import ActivityRepository

            repo = ActivityRepository()
            for row in rows:
                activity = adapt_from_silver(silver_table, row)
                if activity:
                    await repo.upsert(activity)
        except Exception as exc:
            logger.warning(
                "canonical_activity emit failed for table=%s: %s",
                silver_table, exc,
            )

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
