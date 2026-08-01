"""Aether Repositories — Mobile Installations + Push Subscriptions.

Direct-SQL repository for ``mobile_installations`` + ``push_subscriptions``
(alembic 20260822_mobile_installations). Upsert-by-id registration, a unique
(tenant_scope, token_hash) push dedupe, and revocation are semantics the JSONB
BaseRepository cannot express. Raw push tokens are NEVER stored here — only a
token_hash (dedupe); the encrypted token lives in the credential platform.

DDL parity: constants duplicated verbatim from the migration, asserted equal by
tests/unit/test_installation_ddl_parity.py. Backend selection mirrors
repositories/jobs_repo.py (get_pool() None → in-memory dicts; else asyncpg).
Isolation is by ``tenant_scope`` (``t:{tenant_id}`` / ``o:{operator_id}``).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal.instant import to_iso_utc

logger = get_logger("aether.repository.installation")

MOBILE_INSTALLATIONS_DDL = """
CREATE TABLE IF NOT EXISTS mobile_installations (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    app_kind TEXT NOT NULL,
    platform TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    trust_state TEXT NOT NULL DEFAULT 'registered',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
)
"""

PUSH_SUBSCRIPTIONS_DDL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    provider TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    environment TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
)
"""

MOBILE_INSTALLATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_mobile_installations_principal "
    "ON mobile_installations (tenant_scope, principal_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_push_subscriptions_token "
    "ON push_subscriptions (tenant_scope, token_hash)",
    "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_installation "
    "ON push_subscriptions (tenant_scope, installation_id)",
]

_MEM_INSTALLATIONS: dict[str, dict] = {}
_MEM_SUBSCRIPTIONS: dict[str, dict] = {}

_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _mem_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_installation_memory() -> None:
    _MEM_INSTALLATIONS.clear()
    _MEM_SUBSCRIPTIONS.clear()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _iso(v: Any) -> Optional[str]:
    return to_iso_utc(v) if v is not None else None


def _install_row(rec: dict) -> dict:
    return {
        "id": rec["id"], "principal_id": rec["principal_id"],
        "tenant_scope": rec["tenant_scope"], "app_kind": rec["app_kind"],
        "platform": rec["platform"], "bundle_id": rec["bundle_id"],
        "environment": rec["environment"], "trust_state": rec["trust_state"],
        "device_name": (rec.get("data") or {}).get("device_name"),
        "created_at": _iso(rec.get("created_at")), "updated_at": _iso(rec.get("updated_at")),
        "revoked_at": _iso(rec.get("revoked_at")),
    }


def _sub_row(rec: dict) -> dict:
    return {
        "id": rec["id"], "installation_id": rec["installation_id"],
        "principal_id": rec["principal_id"], "platform": rec["platform"],
        "provider": rec["provider"], "token_hash": rec["token_hash"],
        "environment": rec["environment"], "active": rec["active"],
        "created_at": _iso(rec.get("created_at")), "revoked_at": _iso(rec.get("revoked_at")),
    }


class InstallationRepository:
    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._tables_ensured = False

    async def _backend(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        pool = self._pool
        if pool is not None and not self._tables_ensured:
            await pool.execute(MOBILE_INSTALLATIONS_DDL)
            await pool.execute(PUSH_SUBSCRIPTIONS_DDL)
            for idx in MOBILE_INSTALLATION_INDEXES:
                await pool.execute(idx)
            self._tables_ensured = True
        return pool

    # ── Installations ────────────────────────────────────────────────────

    async def register(
        self, *, tenant_scope: str, principal_id: str, installation_id: Optional[str],
        app_kind: str, platform: str, bundle_id: str, environment: str,
        device_name: Optional[str] = None,
    ) -> dict:
        """Upsert an installation by id (re-registration updates in place)."""
        now = utc_now()
        iid = installation_id or _new_id("inst")
        data = {"device_name": device_name}
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                existing = _MEM_INSTALLATIONS.get(iid)
                if existing is not None and existing["tenant_scope"] == tenant_scope:
                    existing.update({
                        "app_kind": app_kind, "platform": platform, "bundle_id": bundle_id,
                        "environment": environment, "trust_state": "registered",
                        "data": data, "updated_at": now, "revoked_at": None,
                    })
                    return _install_row(existing)
                rec = {
                    "id": iid, "tenant_scope": tenant_scope, "principal_id": principal_id,
                    "app_kind": app_kind, "platform": platform, "bundle_id": bundle_id,
                    "environment": environment, "trust_state": "registered", "data": data,
                    "created_at": now, "updated_at": now, "revoked_at": None,
                }
                _MEM_INSTALLATIONS[iid] = rec
                return _install_row(rec)
        row = await pool.fetchrow(
            """
            INSERT INTO mobile_installations (
                id, tenant_scope, principal_id, app_kind, platform, bundle_id,
                environment, trust_state, data, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,'registered',$8::jsonb,$9,$9)
            ON CONFLICT (id) DO UPDATE SET
                app_kind = EXCLUDED.app_kind, platform = EXCLUDED.platform,
                bundle_id = EXCLUDED.bundle_id, environment = EXCLUDED.environment,
                trust_state = 'registered', data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at, revoked_at = NULL
            WHERE mobile_installations.tenant_scope = EXCLUDED.tenant_scope
            RETURNING *
            """,
            iid, tenant_scope, principal_id, app_kind, platform, bundle_id,
            environment, json.dumps(data, default=str), now,
        )
        return _install_row(dict(row))

    async def get(self, tenant_scope: str, installation_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            rec = _MEM_INSTALLATIONS.get(installation_id)
            return _install_row(rec) if rec and rec["tenant_scope"] == tenant_scope else None
        row = await pool.fetchrow(
            "SELECT * FROM mobile_installations WHERE id = $1 AND tenant_scope = $2",
            installation_id, tenant_scope,
        )
        return _install_row(dict(row)) if row is not None else None

    async def list_for_principal(self, tenant_scope: str, principal_id: str) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [_install_row(r) for r in _MEM_INSTALLATIONS.values()
                    if r["tenant_scope"] == tenant_scope and r["principal_id"] == principal_id]
            rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
            return rows
        rows = await pool.fetch(
            "SELECT * FROM mobile_installations WHERE tenant_scope = $1 AND principal_id = $2 "
            "ORDER BY created_at DESC",
            tenant_scope, principal_id,
        )
        return [_install_row(dict(r)) for r in rows]

    async def revoke(self, tenant_scope: str, installation_id: str) -> Optional[dict]:
        """Revoke an installation and deactivate its push subscriptions."""
        now = utc_now()
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                rec = _MEM_INSTALLATIONS.get(installation_id)
                if rec is None or rec["tenant_scope"] != tenant_scope:
                    return None
                rec.update({"trust_state": "revoked", "revoked_at": now, "updated_at": now})
                for sub in _MEM_SUBSCRIPTIONS.values():
                    if sub["installation_id"] == installation_id and sub["tenant_scope"] == tenant_scope:
                        sub["active"] = False
                        sub["revoked_at"] = now
                return _install_row(rec)
        row = await pool.fetchrow(
            "UPDATE mobile_installations SET trust_state = 'revoked', revoked_at = $3, "
            "updated_at = $3 WHERE id = $1 AND tenant_scope = $2 RETURNING *",
            installation_id, tenant_scope, now,
        )
        if row is None:
            return None
        await pool.execute(
            "UPDATE push_subscriptions SET active = false, revoked_at = $3 "
            "WHERE installation_id = $1 AND tenant_scope = $2",
            installation_id, tenant_scope, now,
        )
        return _install_row(dict(row))

    # ── Push subscriptions ───────────────────────────────────────────────

    async def add_subscription(
        self, *, tenant_scope: str, installation_id: str, principal_id: str,
        platform: str, provider: str, token_hash: str, environment: str,
    ) -> dict:
        """Idempotent on (tenant_scope, token_hash): a re-subscribe returns the row."""
        now = utc_now()
        sid = _new_id("push")
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                for sub in _MEM_SUBSCRIPTIONS.values():
                    if sub["tenant_scope"] == tenant_scope and sub["token_hash"] == token_hash:
                        return _sub_row(sub)
                rec = {
                    "id": sid, "tenant_scope": tenant_scope, "installation_id": installation_id,
                    "principal_id": principal_id, "platform": platform, "provider": provider,
                    "token_hash": token_hash, "environment": environment, "active": True,
                    "created_at": now, "revoked_at": None,
                }
                _MEM_SUBSCRIPTIONS[sid] = rec
                return _sub_row(rec)
        inserted = await pool.fetchrow(
            """
            INSERT INTO push_subscriptions (
                id, tenant_scope, installation_id, principal_id, platform, provider,
                token_hash, environment, active, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9)
            ON CONFLICT (tenant_scope, token_hash) DO NOTHING
            RETURNING *
            """,
            sid, tenant_scope, installation_id, principal_id, platform, provider,
            token_hash, environment, now,
        )
        if inserted is not None:
            return _sub_row(dict(inserted))
        existing = await pool.fetchrow(
            "SELECT * FROM push_subscriptions WHERE tenant_scope = $1 AND token_hash = $2",
            tenant_scope, token_hash,
        )
        return _sub_row(dict(existing))

    async def list_subscriptions(self, tenant_scope: str, installation_id: str) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [_sub_row(r) for r in _MEM_SUBSCRIPTIONS.values()
                    if r["tenant_scope"] == tenant_scope and r["installation_id"] == installation_id]
            rows.sort(key=lambda r: r.get("created_at") or "")
            return rows
        rows = await pool.fetch(
            "SELECT * FROM push_subscriptions WHERE tenant_scope = $1 AND installation_id = $2 "
            "ORDER BY created_at ASC",
            tenant_scope, installation_id,
        )
        return [_sub_row(dict(r)) for r in rows]

    async def delete_by_principal(self, tenant_scope: str, principal_id: str) -> int:
        """DSR erasure — remove installations + subscriptions for a subject."""
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                inst = [k for k, r in _MEM_INSTALLATIONS.items()
                        if r["tenant_scope"] == tenant_scope and r["principal_id"] == principal_id]
                sub = [k for k, r in _MEM_SUBSCRIPTIONS.items()
                       if r["tenant_scope"] == tenant_scope and r["principal_id"] == principal_id]
                for k in inst:
                    del _MEM_INSTALLATIONS[k]
                for k in sub:
                    del _MEM_SUBSCRIPTIONS[k]
                return len(inst) + len(sub)
        r1 = await pool.execute(
            "DELETE FROM mobile_installations WHERE tenant_scope = $1 AND principal_id = $2",
            tenant_scope, principal_id,
        )
        r2 = await pool.execute(
            "DELETE FROM push_subscriptions WHERE tenant_scope = $1 AND principal_id = $2",
            tenant_scope, principal_id,
        )
        return _rowcount(r1) + _rowcount(r2)


def _rowcount(result: Any) -> int:
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0


_repo: Optional[InstallationRepository] = None


def get_installation_repository() -> InstallationRepository:
    global _repo
    if _repo is None:
        _repo = InstallationRepository()
    return _repo
