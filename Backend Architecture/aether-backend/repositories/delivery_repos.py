"""Delivery infrastructure repositories.

8 repos covering:
  DeliveryIntentRepository, DeliveryJobRepository, DeliveryAttemptRepository,
  ProviderReceiptRepository, ExternalResourceLinkRepository,
  ExternalOutcomeEventRepository, WebhookInboxRepository, ConnectorCursorRepository.

All extend BaseRepository (JSONB table pattern, in-memory fallback for AETHER_ENV=local).
DeliveryJobRepository adds `lease_next_batch()` with SELECT FOR UPDATE SKIP LOCKED
in PostgreSQL mode and cooperative in-memory lease for local dev.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository, _IN_MEMORY_STORES
from shared.logger.logger import get_logger

logger = get_logger("aether.repositories.delivery")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── DeliveryIntentRepository ────────────────────────────────────────────────

class DeliveryIntentRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("delivery_intents")

    async def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> Optional[dict[str, Any]]:
        results = await self.find_many(
            filters={"idempotency_key": idempotency_key}, limit=1
        )
        return results[0] if results else None


# ─── DeliveryJobRepository ───────────────────────────────────────────────────

class DeliveryJobRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("delivery_jobs")

    async def lease_next_batch(
        self,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[dict[str, Any]]:
        """Atomically claim a batch of runnable jobs for this worker.

        PostgreSQL: SELECT FOR UPDATE SKIP LOCKED so concurrent workers
        never pick the same job.
        In-memory: cooperative state check (single-process only).
        """
        pool = await self._ensure_pool()
        if pool is None:
            # In-memory cooperative lease
            now_str = _now_iso()
            results: list[dict[str, Any]] = []
            for job in list(self._store.values()):
                if len(results) >= batch_size:
                    break
                state = job.get("state", "")
                lease_expires_at = job.get("lease_expires_at", "")
                # Reclaim expired leases so crashed-worker jobs are not stranded forever
                expired_lease = (
                    state == "leased" and lease_expires_at and lease_expires_at <= now_str
                )
                if not expired_lease and state not in ("queued", "failed"):
                    continue
                next_at = job.get("next_attempt_at", "")
                if next_at and next_at > now_str:
                    continue
                expire = (
                    datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
                ).isoformat()
                job["state"] = "leased"
                job["leased_by"] = worker_id
                job["lease_expires_at"] = expire
                job["updated_at"] = now_str
                results.append(job)
            return results

        # PostgreSQL: atomic UPDATE + RETURNING
        await self._ensure_table()
        try:
            rows = await pool.fetch(
                f"""
                UPDATE delivery_jobs
                SET
                    data = jsonb_set(
                        jsonb_set(
                            jsonb_set(data, '{{state}}', '"leased"'),
                            '{{leased_by}}', $1::jsonb
                        ),
                        '{{lease_expires_at}}',
                        to_jsonb((NOW() + ($3 * INTERVAL '1 second'))::text)
                    ),
                    updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM delivery_jobs
                    WHERE
                        (
                            data->>'state' IN ('queued', 'failed')
                            OR (
                                data->>'state' = 'leased'
                                AND (data->>'lease_expires_at')::timestamptz <= NOW()
                            )
                        )
                        AND (data->>'next_attempt_at' IS NULL
                             OR (data->>'next_attempt_at')::timestamptz <= NOW())
                    ORDER BY
                        (data->>'priority')::int ASC,
                        (data->>'next_attempt_at')::timestamptz ASC
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING data
                """,
                json.dumps(worker_id),
                batch_size,
                lease_seconds,
            )
            return [json.loads(r["data"]) for r in rows]
        except Exception as exc:
            logger.warning(f"lease_next_batch failed: {exc}")
            return []

    async def find_for_intent(
        self, intent_id: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"intent_id": intent_id, "tenant_id": tenant_id},
            limit=100,
        )

    async def cancel_for_intent(self, intent_id: str, tenant_id: str) -> int:
        """Cancel all queued/failed jobs for a given intent. Returns count cancelled."""
        jobs = await self.find_for_intent(intent_id, tenant_id)
        count = 0
        for job in jobs:
            if job.get("state") in ("queued", "failed"):
                await self.update(job["id"], {
                    "state": "cancelled",
                    "updated_at": _now_iso(),
                })
                count += 1
        return count


# ─── DeliveryAttemptRepository ───────────────────────────────────────────────

class DeliveryAttemptRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("delivery_attempts")

    async def find_for_job(self, job_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"job_id": job_id}, limit=50, sort_by="created_at", sort_order="asc"
        )


# ─── ProviderReceiptRepository ────────────────────────────────────────────────

class ProviderReceiptRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("provider_receipts")

    async def find_for_intent(self, intent_id: str) -> list[dict[str, Any]]:
        return await self.find_many(filters={"intent_id": intent_id}, limit=50)

    async def find_by_external_id(
        self, external_id: str, provider: str
    ) -> Optional[dict[str, Any]]:
        results = await self.find_many(
            filters={"external_id": external_id, "provider_adapter": provider}, limit=1
        )
        return results[0] if results else None


# ─── ExternalResourceLinkRepository ─────────────────────────────────────────

class ExternalResourceLinkRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("external_resource_links")

    async def find_for_intent(self, intent_id: str) -> list[dict[str, Any]]:
        return await self.find_many(filters={"intent_id": intent_id}, limit=50)


# ─── ExternalOutcomeEventRepository ─────────────────────────────────────────

class ExternalOutcomeEventRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("external_outcome_events")

    async def find_for_external_id(
        self, external_id: str, provider: str
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            filters={"external_id": external_id, "provider": provider}, limit=50
        )


# ─── WebhookInboxRepository ──────────────────────────────────────────────────

class WebhookInboxRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("webhook_inbox")
        import asyncio
        self._claim_lock = asyncio.Lock()

    async def claim_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        """Atomically claim unprocessed inbox records for processing.

        Uses SELECT FOR UPDATE SKIP LOCKED in PostgreSQL mode, and a local
        asyncio lock in in-memory mode to prevent duplicate processing.
        """
        pool = await self._ensure_pool()
        if pool is None:
            # In-memory mode: use asyncio lock to cooperatively claim records
            async with self._claim_lock:
                results = []
                for record in list(self._store.values()):
                    if record.get("processed") or record.get("processing"):
                        continue
                    record["processing"] = True
                    record["processing_started_at"] = _now_iso()
                    results.append(dict(record))
                    if len(results) >= limit:
                        break
                return results

        # PostgreSQL mode: SELECT FOR UPDATE SKIP LOCKED
        await self._ensure_table()
        rows = await pool.fetch(
            f"""
            UPDATE {self.table_name}
            SET data = data || '{{"processing": true, "processing_started_at": "{_now_iso()}"}}'
            WHERE id IN (
                SELECT id FROM {self.table_name}
                WHERE (data->>'processed')::boolean IS NOT TRUE
                  AND (data->>'processing')::boolean IS NOT TRUE
                ORDER BY created_at ASC
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING data
            """,
            limit,
        )
        import json as _json
        return [_json.loads(r["data"]) for r in rows]

    async def find_unprocessed(
        self, provider: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        results = await self.find_many(
            filters={"provider": provider, "processed": False}, limit=limit
        )
        return results

    async def mark_processed(
        self, record_id: str, *, error: Optional[str] = None
    ) -> None:
        update = {"processed": True, "processing": False, "updated_at": _now_iso()}
        if error:
            update["processing_error"] = error
        await self.update(record_id, update)


# ─── ConnectorCursorRepository ───────────────────────────────────────────────

class ConnectorCursorRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("connector_cursors")

    async def get_cursor(
        self, tenant_id: str, connector_type: str
    ) -> Optional[dict[str, Any]]:
        from services.delivery.models import generate_idempotency_key
        cursor_id = generate_idempotency_key(tenant_id, connector_type)
        return await self.find_by_id(cursor_id)

    async def set_cursor(
        self,
        tenant_id: str,
        connector_type: str,
        cursor_value: str,
        event_count: int = 0,
    ) -> dict[str, Any]:
        from services.delivery.models import ConnectorCursor, generate_idempotency_key
        cursor_id = generate_idempotency_key(tenant_id, connector_type)
        now = _now_iso()
        data = ConnectorCursor(
            id=cursor_id,
            tenant_id=tenant_id,
            connector_type=connector_type,
            cursor_value=cursor_value,
            last_synced_at=now,
            last_event_count=event_count,
            updated_at=now,
        ).model_dump()
        return await self.insert(cursor_id, data)
