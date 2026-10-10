"""Durable metadata-only quarantine for denied connector webhooks."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from repositories.repos import BaseRepository


class WebhookQuarantineRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("webhook_quarantine")

    async def quarantine(
        self,
        *,
        tenant_id: str,
        connector_type: str,
        raw_body: bytes,
        reason_code: str,
        inbox_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        retention_days: int = 7,
    ) -> dict[str, Any]:
        quarantine_id = f"whq_{uuid4().hex}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=retention_days)
        payload = {
            "id": quarantine_id,
            "tenant_id": tenant_id,
            "provider": connector_type,
            "connector_type": connector_type,
            "reason_code": reason_code,
            "policy_decision_id": policy_decision_id,
            "encrypted_payload_ref": (
                f"webhook_inbox:{inbox_id}" if inbox_id else None
            ),
            "payload_sha256": hashlib.sha256(raw_body).hexdigest(),
            "payload_size_bytes": len(raw_body),
            "legal_hold": False,
            "expires_at": expires_at.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        pool = await self._ensure_pool()
        if pool is None:
            self._store[quarantine_id] = payload
            return payload

        await self._ensure_table()
        await pool.execute(
            """
            INSERT INTO webhook_quarantine
                (id, tenant_id, provider, expires_at, legal_hold, data,
                 created_at, updated_at)
            VALUES ($1, $2, $3, $4, FALSE, $5::jsonb, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            quarantine_id,
            tenant_id,
            connector_type,
            expires_at,
            json.dumps(payload, default=str),
        )
        return payload


webhook_quarantine = WebhookQuarantineRepository()
