"""Typed asyncpg repositories for the campaign registry domain.

These repositories bypass the generic JSONB BaseRepository and write to
the structured Alembic-managed tables introduced in migration 20260627_campaign_registry.

Pool policy
-----------
Canonical campaign identity must never be transient: two processes must not mint
different UUIDs for the same external campaign, and an identity must survive a
restart. Outside local development that invariant is enforced by requiring a real
pool — :func:`_require_pool` raises when one is absent rather than falling back.

A DB-free in-memory path is retained for local development and tests only, and is
structurally unreachable anywhere else. This module previously documented "no
in-memory fallback" while implementing one in eleven places and hard-failing in a
twelfth, which meant a misconfigured production process could silently fabricate
campaign identity that vanished on restart. The guard below is what makes the
stated invariant true, rather than a comment asserting it.
"""

from __future__ import annotations

import os
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from repositories.repos import get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.campaign.repository")

# In-memory stores backing the local-development path. Reachable only when
# _require_pool() has confirmed the environment permits a DB-free run.
_LOCAL_CAMPAIGNS: dict[str, dict] = {}
_LOCAL_EXTERNAL_REFS: dict[str, dict] = {}
_LOCAL_ALIASES: dict[str, dict] = {}
_LOCAL_REVIEWS: dict[str, dict] = {}

# Environments permitted to run without a database. Everything else — including
# integration, which is deliberately production-shaped — must have a real pool.
_POOL_OPTIONAL_ENVIRONMENTS = frozenset({"local", "dev", "test"})


async def _pool():
    return await get_pool()


def _pool_is_optional() -> bool:
    """Whether this environment may run the campaign registry without a pool.

    Read at call time rather than import time so a test or a process that sets
    AETHER_ENV after import is still evaluated against the value in force.
    """
    return os.environ.get("AETHER_ENV", "local") in _POOL_OPTIONAL_ENVIRONMENTS


def _require_pool(pool: Any, operation: str) -> None:
    """Fail closed when a pool is absent in an environment that requires one.

    Raising here is the point: the alternative is minting a campaign UUID in
    process memory, which two workers would do differently for the same external
    campaign and which would not survive a restart.
    """
    if pool is None and not _pool_is_optional():
        raise RuntimeError(
            f"campaign registry {operation} requires a database pool in "
            f"AETHER_ENV={os.environ.get('AETHER_ENV', 'local')}; refusing to "
            "fabricate transient campaign identity in memory"
        )


class _PoolBackedRepository:
    """Base for the campaign repositories, allowing the pool to be injected.

    These repositories originally reached the database only through the
    module-level :func:`_pool` lookup and defined no ``__init__``, while callers
    on both sides assumed constructor injection: ``routes.py`` constructs
    ``ExternalRefRepository(None)`` and ``AliasRepository(None)``, and the test
    suite constructs all four with a fake pool. Both raised
    ``TypeError: ... takes no arguments`` — the routes ones at runtime, on any
    request reaching those handlers.

    That went unnoticed because ``Backend Architecture/aether-backend/tests/``
    was executed by no gate.

    Passing ``pool=None`` keeps the original behaviour (resolve lazily via
    ``get_pool()``), so the no-argument call sites in ``resolver.py`` and
    ``registry.py`` are unaffected.
    """

    def __init__(self, pool: Any = None) -> None:
        self._injected_pool = pool

    async def _acquire_pool(self) -> Any:
        """Return the injected pool, or resolve the process-wide one.

        Injection is checked first so a test double is never silently bypassed
        in favour of a real connection.

        The environment guard lives here rather than at each of the twelve call
        sites so no future method can reach an in-memory store without passing
        it. Returning ``None`` is only possible where a DB-free run is allowed.
        """
        pool = self._injected_pool
        if pool is None:
            pool = await _pool()
        _require_pool(pool, type(self).__name__)
        return pool


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict:
    return dict(row)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── CampaignRegistryRepository ────────────────────────────────────────────────

class CampaignRegistryRepository(_PoolBackedRepository):
    """Typed repository for the campaigns table."""

    async def get_by_id(self, tenant_id: str, campaign_id: UUID) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            record = _LOCAL_CAMPAIGNS.get(str(campaign_id))
            return record if record and record.get("tenant_id") == tenant_id else None
        row = await pool.fetchrow(
            """
            SELECT * FROM campaigns
            WHERE tenant_id = $1 AND campaign_id = $2
            """,
            tenant_id, campaign_id,
        )
        return _row_to_dict(row) if row else None

    async def get_by_id_or_fail(self, tenant_id: str, campaign_id: UUID) -> dict:
        record = await self.get_by_id(tenant_id, campaign_id)
        if record is None:
            raise ValueError(f"campaign {campaign_id} not found for tenant {tenant_id}")
        return record

    async def create(
        self,
        tenant_id: str,
        name: str,
        *,
        channel: Optional[str] = None,
        origin: str = "custom",
        primary_platform: Optional[str] = None,
        source_connector_id: Optional[str] = None,
        status: str = "active",
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        budget_usd: Optional[Decimal] = None,
        first_seen_at: Optional[datetime] = None,
        last_seen_at: Optional[datetime] = None,
        properties: Optional[dict] = None,
    ) -> dict:
        pool = await self._acquire_pool()
        now = _now()
        if pool is None:
            record = {
                "campaign_id": uuid.uuid4(),
                "tenant_id": tenant_id, "name": name, "status": status,
                "channel": channel, "origin": origin, "primary_platform": primary_platform,
                "source_connector_id": source_connector_id,
                "sync_status": "not_synced" if origin == "custom" else "pending",
                "first_seen_at": first_seen_at or now, "last_seen_at": last_seen_at or now,
                "archived_at": None, "display_name_override": None, "properties": properties or {},
                "schema_version": 1, "created_at": now, "updated_at": now,
            }
            _LOCAL_CAMPAIGNS[str(record["campaign_id"])] = record
            return record
        row = await pool.fetchrow(
            """
            INSERT INTO campaigns (
                tenant_id, name, channel, origin, primary_platform, source_connector_id,
                status, start_at, end_at, budget_usd, first_seen_at, last_seen_at,
                sync_status, properties, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$15)
            RETURNING *
            """,
            tenant_id, name, channel, origin, primary_platform, source_connector_id,
            status, start_at, end_at, budget_usd,
            first_seen_at or now, last_seen_at or now,
            "not_synced" if origin == "custom" else "pending",
            json.dumps(properties or {}),
            now,
        )
        return _row_to_dict(row)

    async def update_metadata(
        self,
        tenant_id: str,
        campaign_id: UUID,
        *,
        name: Optional[str] = None,
        provider_status: Optional[str] = None,
        sync_status: Optional[str] = None,
        last_seen_at: Optional[datetime] = None,
        archived_at: Optional[datetime] = None,
    ) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            return None
        sets: list[str] = ["updated_at = NOW()"]
        params: list[Any] = [tenant_id, campaign_id]
        idx = 3
        for col, val in [
            ("name", name),
            ("provider_status", provider_status),
            ("sync_status", sync_status),
            ("last_seen_at", last_seen_at),
            ("archived_at", archived_at),
        ]:
            if val is not None:
                sets.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        row = await pool.fetchrow(
            f"UPDATE campaigns SET {', '.join(sets)} WHERE tenant_id = $1 AND campaign_id = $2 RETURNING *",
            *params,
        )
        return _row_to_dict(row) if row else None

    async def list_campaigns(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        origin: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            return []
        conditions = ["tenant_id = $1", "archived_at IS NULL"]
        params: list[Any] = [tenant_id]
        idx = 2
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if origin:
            conditions.append(f"origin = ${idx}")
            params.append(origin)
            idx += 1
        if platform:
            conditions.append(f"primary_platform = ${idx}")
            params.append(platform)
            idx += 1
        params.extend([limit, offset])
        rows = await pool.fetch(
            f"""
            SELECT * FROM campaigns WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
        return [_row_to_dict(r) for r in rows]


# ── ExternalRefRepository ─────────────────────────────────────────────────────

class ExternalRefRepository(_PoolBackedRepository):
    """Typed repository for campaign_external_refs."""

    async def get_exact(
        self,
        tenant_id: str,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
    ) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            key = f"{tenant_id}::{platform}::{external_account_id}::{external_campaign_id}"
            return _LOCAL_EXTERNAL_REFS.get(key)
        row = await pool.fetchrow(
            """
            SELECT * FROM campaign_external_refs
            WHERE tenant_id = $1 AND platform = $2
              AND external_account_id = $3 AND external_campaign_id = $4
            """,
            tenant_id, platform, external_account_id, external_campaign_id,
        )
        return _row_to_dict(row) if row else None

    async def upsert(
        self,
        tenant_id: str,
        campaign_id: UUID,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
        *,
        external_campaign_name: Optional[str] = None,
        external_status: Optional[str] = None,
        source_connector_id: Optional[str] = None,
        raw_metadata: Optional[dict] = None,
    ) -> dict:
        pool = await self._acquire_pool()
        if pool is None:
            key = f"{tenant_id}::{platform}::{external_account_id}::{external_campaign_id}"
            now = _now()
            existing = _LOCAL_EXTERNAL_REFS.get(key)
            if existing:
                existing.update({"external_campaign_name": external_campaign_name, "external_status": external_status, "last_seen_at": now, "updated_at": now})
                return existing
            record = {
                "external_ref_id": uuid.uuid4(), "tenant_id": tenant_id, "campaign_id": campaign_id,
                "platform": platform, "external_account_id": external_account_id,
                "external_campaign_id": external_campaign_id, "external_campaign_name": external_campaign_name,
                "external_status": external_status, "source_connector_id": source_connector_id,
                "raw_metadata": raw_metadata or {}, "schema_version": 1,
                "first_seen_at": now, "last_seen_at": now, "created_at": now, "updated_at": now,
            }
            _LOCAL_EXTERNAL_REFS[key] = record
            return record
        row = await pool.fetchrow(
            """
            INSERT INTO campaign_external_refs (
                tenant_id, campaign_id, platform, external_account_id,
                external_campaign_id, external_campaign_name, external_status,
                source_connector_id, raw_metadata, last_seen_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (tenant_id, platform, external_account_id, external_campaign_id)
            DO UPDATE SET
                external_campaign_name = EXCLUDED.external_campaign_name,
                external_status        = EXCLUDED.external_status,
                source_connector_id    = COALESCE(EXCLUDED.source_connector_id, campaign_external_refs.source_connector_id),
                raw_metadata           = EXCLUDED.raw_metadata,
                last_seen_at           = NOW(),
                updated_at             = NOW()
            RETURNING *
            """,
            tenant_id, campaign_id, platform, external_account_id,
            external_campaign_id, external_campaign_name, external_status,
            source_connector_id, json.dumps(raw_metadata or {}),
        )
        return _row_to_dict(row)

    async def list_for_campaign(self, tenant_id: str, campaign_id: UUID) -> list[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            return []
        rows = await pool.fetch(
            "SELECT * FROM campaign_external_refs WHERE tenant_id = $1 AND campaign_id = $2 ORDER BY created_at",
            tenant_id, campaign_id,
        )
        return [_row_to_dict(r) for r in rows]


# ── AliasRepository ───────────────────────────────────────────────────────────

class AliasRepository(_PoolBackedRepository):
    """Typed repository for campaign_aliases."""

    async def get_active(
        self,
        tenant_id: str,
        alias_type: str,
        alias_value_normalized: str,
    ) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            # Mirrors the SQL predicate below. Returning None unconditionally
            # here made every alias written to the local store invisible to
            # resolution, so the resolver reported "unresolved" for aliases it
            # had just been given.
            for record in _LOCAL_ALIASES.values():
                if (
                    record["tenant_id"] == tenant_id
                    and record["alias_type"] == alias_type
                    and record["alias_value_normalized"] == alias_value_normalized
                    and record["valid_until"] is None
                ):
                    return record
            return None
        row = await pool.fetchrow(
            """
            SELECT * FROM campaign_aliases
            WHERE tenant_id = $1 AND alias_type = $2
              AND alias_value_normalized = $3 AND valid_until IS NULL
            """,
            tenant_id, alias_type, alias_value_normalized,
        )
        return _row_to_dict(row) if row else None

    async def get_active_batch(
        self,
        tenant_id: str,
        lookups: list[tuple[str, str]],
    ) -> dict[tuple[str, str], dict]:
        """Batch lookup: lookups is list of (alias_type, alias_value_normalized)."""
        if not lookups:
            return {}
        pool = await self._acquire_pool()
        if pool is None:
            wanted = set(lookups)
            result: dict[tuple[str, str], dict] = {}
            for record in _LOCAL_ALIASES.values():
                key = (record["alias_type"], record["alias_value_normalized"])
                if (
                    record["tenant_id"] == tenant_id
                    and record["valid_until"] is None
                    and key in wanted
                ):
                    result[key] = record
            return result
        # Use unnest for a single round-trip
        types = [t for t, _ in lookups]
        values = [v for _, v in lookups]
        rows = await pool.fetch(
            """
            SELECT ca.*
            FROM campaign_aliases ca
            JOIN unnest($2::text[], $3::text[]) AS lk(alias_type, alias_value_normalized)
              ON ca.alias_type = lk.alias_type
             AND ca.alias_value_normalized = lk.alias_value_normalized
            WHERE ca.tenant_id = $1 AND ca.valid_until IS NULL
            """,
            tenant_id, types, values,
        )
        result: dict[tuple[str, str], dict] = {}
        for row in rows:
            d = _row_to_dict(row)
            result[(d["alias_type"], d["alias_value_normalized"])] = d
        return result

    async def create(
        self,
        tenant_id: str,
        campaign_id: UUID,
        alias_type: str,
        alias_value: str,
        alias_value_normalized: str,
        *,
        platform: Optional[str] = None,
        external_account_id: Optional[str] = None,
        source: Optional[str] = None,
        medium: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        source_connector_id: Optional[str] = None,
        created_by: str = "system",
        provenance: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create alias; returns None if an active alias already exists (conflict)."""
        pool = await self._acquire_pool()
        if pool is None:
            now = _now()
            # Mirror the table's partial unique constraint: an alias value may be
            # reused only once its previous binding has been expired. Returning
            # None rather than raising matches the SQL path, where a unique
            # violation is a conflict signal and not an error.
            for existing in _LOCAL_ALIASES.values():
                if (
                    existing["tenant_id"] == tenant_id
                    and existing["alias_type"] == alias_type
                    and existing["alias_value_normalized"] == alias_value_normalized
                    and existing["valid_until"] is None
                ):
                    return None
            record = {
                "alias_id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "alias_type": alias_type,
                "alias_value": alias_value,
                "alias_value_normalized": alias_value_normalized,
                "platform": platform,
                "external_account_id": external_account_id,
                "source": source,
                "medium": medium,
                "valid_from": valid_from or now,
                "valid_until": None,
                "source_connector_id": source_connector_id,
                "created_by": created_by,
                "provenance": provenance or {},
                "created_at": now,
                "updated_at": now,
            }
            _LOCAL_ALIASES[str(record["alias_id"])] = record
            return record
        try:
            row = await pool.fetchrow(
                """
                INSERT INTO campaign_aliases (
                    tenant_id, campaign_id, alias_type, alias_value, alias_value_normalized,
                    platform, external_account_id, source, medium, valid_from,
                    source_connector_id, created_by, provenance
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                RETURNING *
                """,
                tenant_id, campaign_id, alias_type, alias_value, alias_value_normalized,
                platform, external_account_id, source, medium, valid_from,
                source_connector_id, created_by, json.dumps(provenance or {}),
            )
            return _row_to_dict(row) if row else None
        except Exception as exc:
            if "unique" in str(exc).lower():
                return None  # conflict — active alias already exists
            raise

    async def expire(self, tenant_id: str, alias_id: UUID) -> bool:
        pool = await self._acquire_pool()
        if pool is None:
            record = _LOCAL_ALIASES.get(str(alias_id))
            # Only an active alias owned by this tenant can be expired, matching
            # the WHERE clause below; returning False for anything else keeps the
            # "did this actually change something" contract intact.
            if (
                record is None
                or record["tenant_id"] != tenant_id
                or record["valid_until"] is not None
            ):
                return False
            now = _now()
            record["valid_until"] = now
            record["updated_at"] = now
            return True
        result = await pool.execute(
            "UPDATE campaign_aliases SET valid_until = NOW(), updated_at = NOW() WHERE tenant_id = $1 AND alias_id = $2 AND valid_until IS NULL",
            tenant_id, alias_id,
        )
        return result.split()[-1] != "0"

    async def list_for_campaign(self, tenant_id: str, campaign_id: UUID) -> list[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            # Previously returned [] unconditionally, so an alias written by
            # create() was invisible to every reader — _LOCAL_ALIASES was
            # declared but never actually read by anything.
            return sorted(
                (
                    record
                    for record in _LOCAL_ALIASES.values()
                    if record["tenant_id"] == tenant_id
                    and str(record["campaign_id"]) == str(campaign_id)
                ),
                key=lambda record: record["created_at"],
            )
        rows = await pool.fetch(
            "SELECT * FROM campaign_aliases WHERE tenant_id = $1 AND campaign_id = $2 ORDER BY created_at",
            tenant_id, campaign_id,
        )
        return [_row_to_dict(r) for r in rows]


# ── MappingReviewRepository ───────────────────────────────────────────────────

class MappingReviewRepository(_PoolBackedRepository):
    """Typed repository for campaign_resolution_reviews."""

    async def get_or_create_open(
        self,
        tenant_id: str,
        evidence_hash: str,
        evidence: dict,
        candidate_campaign_ids: list[UUID],
    ) -> dict:
        """Upsert: increment observed_count on existing open review, else create."""
        pool = await self._acquire_pool()
        if pool is None:
            key = f"{tenant_id}::open::{evidence_hash}"
            now = _now()
            existing = _LOCAL_REVIEWS.get(key)
            if existing:
                existing["observed_count"] += 1
                existing["last_seen_at"] = now
                return existing
            record = {
                "review_id": uuid.uuid4(), "tenant_id": tenant_id, "status": "open",
                "evidence": evidence, "evidence_hash": evidence_hash,
                "candidate_campaign_ids": [str(c) for c in candidate_campaign_ids],
                "observed_count": 1, "affected_touchpoints": 0,
                "first_seen_at": now, "last_seen_at": now,
                "resolved_campaign_id": None, "resolved_by": None, "resolved_at": None, "resolution_note": None,
                "created_at": now, "updated_at": now,
            }
            _LOCAL_REVIEWS[key] = record
            return record
        candidate_json = json.dumps([str(c) for c in candidate_campaign_ids])
        row = await pool.fetchrow(
            """
            INSERT INTO campaign_resolution_reviews (
                tenant_id, status, evidence, evidence_hash,
                candidate_campaign_ids, observed_count, first_seen_at, last_seen_at
            ) VALUES ($1, 'open', $2, $3, $4, 1, NOW(), NOW())
            ON CONFLICT (tenant_id, evidence_hash, status)
            DO UPDATE SET
                observed_count         = campaign_resolution_reviews.observed_count + 1,
                last_seen_at           = NOW(),
                candidate_campaign_ids = EXCLUDED.candidate_campaign_ids,
                updated_at             = NOW()
            RETURNING *
            """,
            tenant_id, json.dumps(evidence), evidence_hash, candidate_json,
        )
        return _row_to_dict(row)

    async def resolve(
        self,
        tenant_id: str,
        review_id: UUID,
        campaign_id: UUID,
        resolved_by: str,
        note: Optional[str] = None,
    ) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            return self._local_set_status(
                tenant_id, review_id, "resolved",
                extra={
                    "resolved_campaign_id": campaign_id,
                    "resolved_by": resolved_by,
                    "resolved_at": _now(),
                    "resolution_note": note,
                },
            )
        row = await pool.fetchrow(
            """
            UPDATE campaign_resolution_reviews
            SET status = 'resolved', resolved_campaign_id = $3,
                resolved_by = $4, resolved_at = NOW(), resolution_note = $5, updated_at = NOW()
            WHERE tenant_id = $1 AND review_id = $2 AND status = 'open'
            RETURNING *
            """,
            tenant_id, review_id, campaign_id, resolved_by, note,
        )
        return _row_to_dict(row) if row else None

    @staticmethod
    def _local_set_status(
        tenant_id: str, review_id: UUID, status: str, extra: Optional[dict] = None
    ) -> Optional[dict]:
        """Local-store status transition, mirroring the SQL semantics.

        The store key embeds the status because the table's unique constraint is
        partial — (tenant, evidence_hash, status='open') — so a resolved review
        must vacate the open slot, letting the same evidence legitimately open a
        fresh review later. Mutating status in place under the old key would
        instead resurface the closed review as the open one.
        """
        for key, record in list(_LOCAL_REVIEWS.items()):
            if (
                record["tenant_id"] == tenant_id
                and str(record["review_id"]) == str(review_id)
            ):
                del _LOCAL_REVIEWS[key]
                record["status"] = status
                record["updated_at"] = _now()
                if extra:
                    record.update(extra)
                _LOCAL_REVIEWS[
                    f"{tenant_id}::{status}::{record['evidence_hash']}"
                ] = record
                return record
        return None

    async def set_status(self, tenant_id: str, review_id: UUID, status: str) -> Optional[dict]:
        pool = await self._acquire_pool()
        if pool is None:
            return self._local_set_status(tenant_id, review_id, status)
        row = await pool.fetchrow(
            "UPDATE campaign_resolution_reviews SET status = $3, updated_at = NOW() WHERE tenant_id = $1 AND review_id = $2 RETURNING *",
            tenant_id, review_id, status,
        )
        return _row_to_dict(row) if row else None

    async def list_by_status(
        self,
        tenant_id: str,
        status: str = "open",
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> list[dict]:
        """List reviews in one status, newest first.

        The status filter exists because the route has always exposed one
        (``status: str = Query(default="open")``) while this layer could only
        ever answer for open reviews, so a caller asking for resolved or ignored
        reviews was answered with an unrelated result set at best.
        """
        pool = await self._acquire_pool()
        if pool is None:
            reviews = [
                record
                for record in _LOCAL_REVIEWS.values()
                if record["tenant_id"] == tenant_id and record["status"] == status
            ]
            reviews.sort(key=lambda record: record["first_seen_at"], reverse=True)
            if cursor:
                reviews = [r for r in reviews if r["first_seen_at"] < cursor]
            return reviews[:limit]
        if cursor:
            rows = await pool.fetch(
                "SELECT * FROM campaign_resolution_reviews WHERE tenant_id = $1 AND status = $2 AND first_seen_at < $3 ORDER BY first_seen_at DESC LIMIT $4",
                tenant_id, status, cursor, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM campaign_resolution_reviews WHERE tenant_id = $1 AND status = $2 ORDER BY first_seen_at DESC LIMIT $3",
                tenant_id, status, limit,
            )
        return [_row_to_dict(r) for r in rows]

    async def increment_affected_touchpoints(self, tenant_id: str, evidence_hash: str, count: int = 1) -> None:
        pool = await self._acquire_pool()
        if pool is None:
            return
        await pool.execute(
            "UPDATE campaign_resolution_reviews SET affected_touchpoints = affected_touchpoints + $3, updated_at = NOW() WHERE tenant_id = $1 AND evidence_hash = $2 AND status = 'open'",
            tenant_id, evidence_hash, count,
        )
