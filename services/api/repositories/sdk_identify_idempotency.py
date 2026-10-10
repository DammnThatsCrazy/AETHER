"""Durable tenant-scoped idempotency claims for SDK identify requests.

The record is claimed before identify side effects begin. A pending claim is
never automatically taken over: after a process crash the outcome may be
ambiguous across the identity repository and event broker, so replaying it
could duplicate effects. Completed outcomes contain only non-PII response
fields; caller identifiers are reconstructed from a fingerprint-matched retry.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now

SDK_IDENTIFY_PENDING_STALE_AFTER = timedelta(minutes=15)

SDK_IDENTIFY_IDEMPOTENCY_DDL = """
CREATE TABLE IF NOT EXISTS sdk_identify_idempotency (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key),
    CHECK ((state = 'pending' AND response IS NULL) OR
           (state = 'completed' AND response IS NOT NULL))
)
"""

_MEM_ROWS: dict[tuple[str, str], dict[str, Any]] = {}
_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _memory_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_sdk_identify_idempotency_memory() -> None:
    _MEM_ROWS.clear()


class SDKIdentifyIdempotencyRepository:
    async def claim(self, tenant_id: str, key: str, fingerprint: str) -> dict[str, Any]:
        pool = await get_pool()
        token = uuid.uuid4().hex
        if pool is None:
            async with _memory_lock():
                entry_key = (tenant_id, key)
                row = _MEM_ROWS.get(entry_key)
                if row is None:
                    _MEM_ROWS[entry_key] = {
                        "fingerprint": fingerprint,
                        "claim_token": token,
                        "state": "pending",
                        "response": None,
                        "updated_at": utc_now(),
                    }
                    return {"status": "claimed", "claim_token": token}
                if row["fingerprint"] != fingerprint:
                    return {"status": "conflict"}
                if row["state"] == "completed":
                    return {"status": "replay", "response": copy.deepcopy(row["response"])}
                updated_at = row["updated_at"]
                if (utc_now() - updated_at) >= SDK_IDENTIFY_PENDING_STALE_AFTER:
                    return {"status": "stale"}
                return {"status": "in_progress"}

        async with pool.acquire() as conn:
            await conn.execute(SDK_IDENTIFY_IDEMPOTENCY_DDL)
            inserted = await conn.fetchrow(
                """INSERT INTO sdk_identify_idempotency
                   (tenant_id, idempotency_key, request_fingerprint, claim_token, state)
                   VALUES ($1, $2, $3, $4, 'pending')
                   ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                   RETURNING claim_token""",
                tenant_id, key, fingerprint, token,
            )
            if inserted:
                return {"status": "claimed", "claim_token": inserted["claim_token"]}
            row = await conn.fetchrow(
                """SELECT request_fingerprint, state, response, updated_at
                   FROM sdk_identify_idempotency
                   WHERE tenant_id = $1 AND idempotency_key = $2""",
                tenant_id, key,
            )
        if row is None:
            # A concurrent delete is not expected; fail closed rather than run.
            return {"status": "in_progress"}
        if row["request_fingerprint"] != fingerprint:
            return {"status": "conflict"}
        if row["state"] == "completed":
            response = row["response"]
            if isinstance(response, str):
                response = json.loads(response)
            return {"status": "replay", "response": response}
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated_at) >= SDK_IDENTIFY_PENDING_STALE_AFTER:
            return {"status": "stale"}
        return {"status": "in_progress"}

    async def complete(
        self, tenant_id: str, key: str, claim_token: str, response: dict[str, Any]
    ) -> bool:
        pool = await get_pool()
        if pool is None:
            async with _memory_lock():
                row = _MEM_ROWS.get((tenant_id, key))
                if not row or row["claim_token"] != claim_token or row["state"] != "pending":
                    return False
                row["state"] = "completed"
                row["response"] = copy.deepcopy(response)
                row["updated_at"] = utc_now()
                return True
        async with pool.acquire() as conn:
            await conn.execute(SDK_IDENTIFY_IDEMPOTENCY_DDL)
            status = await conn.execute(
                """UPDATE sdk_identify_idempotency
                   SET state = 'completed', response = $4::jsonb, updated_at = now()
                   WHERE tenant_id = $1 AND idempotency_key = $2
                     AND claim_token = $3 AND state = 'pending'""",
                tenant_id, key, claim_token, json.dumps(response, separators=(",", ":")),
            )
        return status.endswith(" 1")


_repository: Optional[SDKIdentifyIdempotencyRepository] = None


def get_sdk_identify_idempotency_repository() -> SDKIdentifyIdempotencyRepository:
    global _repository
    if _repository is None:
        _repository = SDKIdentifyIdempotencyRepository()
    return _repository
