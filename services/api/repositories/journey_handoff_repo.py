"""Aether Repositories — journey handoff tokens (cross-device journey continuity).

Direct-SQL repository for ``journey_handoffs`` (alembic 20261022_journey_handoffs).
Redemption must be atomic and single-use, which the JSONB BaseRepository cannot
express, so redeem is one conditional UPDATE. Only the SHA-256 of a token is
stored. Backend selection mirrors repositories/continuation_repo.py: no pool
(local mode) -> shared in-memory dict under an asyncio.Lock with identical
semantics.

DDL parity: the constants below are duplicated VERBATIM from the migration and
asserted equal by tests/unit/test_journey_handoff_ddl_parity.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now

JOURNEY_HANDOFFS_DDL = """
CREATE TABLE IF NOT EXISTS journey_handoffs (
    token_hash TEXT PRIMARY KEY,
    handoff_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    app_namespace TEXT NOT NULL,
    journey_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_anonymous_id TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'issued',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    redeemed_at TIMESTAMPTZ,
    redeemed_session_id TEXT,
    redeemed_anonymous_id TEXT,
    redeemed_platform TEXT
)
"""

JOURNEY_HANDOFF_INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_journey_handoffs_id "
    "ON journey_handoffs (tenant_id, handoff_id)",
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_journey "
    "ON journey_handoffs (tenant_id, journey_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_journey_handoffs_expiry "
    "ON journey_handoffs (expires_at)",
]

# Redeemed/expired rows are kept this long for the per-journey audit listing.
RETAIN_DAYS = 90

_MEM: dict[str, dict[str, Any]] = {}
_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _mem_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_journey_handoff_memory() -> None:
    """Test helper."""
    _MEM.clear()


def _public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in dict(row).items() if k != "token_hash"}
    for key in ("expires_at", "created_at", "redeemed_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


class JourneyHandoffRepository:
    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._tables_ensured = False

    async def _backend(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._tables_ensured:
            await self._pool.execute(JOURNEY_HANDOFFS_DDL)
            for idx in JOURNEY_HANDOFF_INDEXES:
                await self._pool.execute(idx)
            self._tables_ensured = True
        return self._pool

    async def issue(self, record: dict[str, Any]) -> dict[str, Any]:
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                _MEM[record["token_hash"]] = {**record, "state": "issued"}
            return _public(record)
        await pool.execute(
            "INSERT INTO journey_handoffs (token_hash, handoff_id, tenant_id, app_namespace, "
            "journey_id, source_session_id, source_anonymous_id, source_platform, expires_at, "
            "created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            record["token_hash"], record["handoff_id"], record["tenant_id"],
            record["app_namespace"], record["journey_id"], record["source_session_id"],
            record["source_anonymous_id"], record["source_platform"],
            record["expires_at"], record["created_at"],
        )
        return _public(record)

    async def redeem(
        self,
        *,
        tenant_id: str,
        app_namespace: str,
        token_hash: str,
        session_id: str,
        anonymous_id: str,
        platform: str,
        now: Optional[datetime] = None,
    ) -> tuple[Optional[dict[str, Any]], str]:
        """Atomically consume a token. Returns (record, "") or (None, reason).

        Reasons (for logs / metrics only — callers must not distinguish them to
        clients): not_found, wrong_scope, expired, already_redeemed.
        """
        now = now or utc_now()
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                row = _MEM.get(token_hash)
                if row is None:
                    return None, "not_found"
                if row["tenant_id"] != tenant_id or row["app_namespace"] != app_namespace:
                    return None, "wrong_scope"
                if row["state"] != "issued":
                    return None, "already_redeemed"
                if row["expires_at"] <= now:
                    return None, "expired"
                row.update(
                    state="redeemed", redeemed_at=now, redeemed_session_id=session_id,
                    redeemed_anonymous_id=anonymous_id, redeemed_platform=platform,
                )
                return _public(row), ""
        updated = await pool.fetchrow(
            "UPDATE journey_handoffs SET state='redeemed', redeemed_at=$5, "
            "redeemed_session_id=$6, redeemed_anonymous_id=$7, redeemed_platform=$8 "
            "WHERE token_hash=$1 AND tenant_id=$2 AND app_namespace=$3 AND state='issued' "
            "AND expires_at > $4 RETURNING *",
            token_hash, tenant_id, app_namespace, now, now, session_id, anonymous_id, platform,
        )
        if updated is not None:
            return _public(dict(updated)), ""
        existing = await pool.fetchrow(
            "SELECT tenant_id, app_namespace, state FROM journey_handoffs WHERE token_hash=$1",
            token_hash,
        )
        if existing is None:
            return None, "not_found"
        if existing["tenant_id"] != tenant_id or existing["app_namespace"] != app_namespace:
            return None, "wrong_scope"
        return None, "already_redeemed" if existing["state"] != "issued" else "expired"

    async def list_for_journey(
        self, tenant_id: str, journey_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                rows = [
                    _public(r) for r in _MEM.values()
                    if r["tenant_id"] == tenant_id and r["journey_id"] == journey_id
                ]
            rows.sort(key=lambda r: str(r["created_at"]), reverse=True)
            return rows[:limit]
        rows = await pool.fetch(
            "SELECT * FROM journey_handoffs WHERE tenant_id=$1 AND journey_id=$2 "
            "ORDER BY created_at DESC LIMIT $3",
            tenant_id, journey_id, limit,
        )
        return [_public(dict(r)) for r in rows]

    async def sweep_expired(self, retain_days: int = RETAIN_DAYS) -> int:
        """Delete rows created more than ``retain_days`` ago (redeemed or not)."""
        cutoff = utc_now() - timedelta(days=retain_days)
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                stale = [k for k, r in _MEM.items() if r["created_at"] < cutoff]
                for k in stale:
                    del _MEM[k]
                return len(stale)
        return _rowcount(await pool.execute(
            "DELETE FROM journey_handoffs WHERE created_at < $1", cutoff
        ))

    async def delete_by_anonymous_id(self, tenant_id: str, anonymous_id: str) -> int:
        """DSR erasure hook: remove every handoff naming this anonymous ID at either end."""
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                hit = [
                    k for k, r in _MEM.items()
                    if r["tenant_id"] == tenant_id and anonymous_id in (
                        r["source_anonymous_id"], r.get("redeemed_anonymous_id"),
                    )
                ]
                for k in hit:
                    del _MEM[k]
                return len(hit)
        return _rowcount(await pool.execute(
            "DELETE FROM journey_handoffs WHERE tenant_id=$1 AND "
            "(source_anonymous_id=$2 OR redeemed_anonymous_id=$2)",
            tenant_id, anonymous_id,
        ))


def _rowcount(result: Any) -> int:
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


_repo: Optional[JourneyHandoffRepository] = None


def get_journey_handoff_repository() -> JourneyHandoffRepository:
    global _repo
    if _repo is None:
        _repo = JourneyHandoffRepository()
    return _repo
