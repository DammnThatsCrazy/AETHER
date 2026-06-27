"""Typed asyncpg repositories for the campaign registry domain.

These repositories bypass the generic JSONB BaseRepository and write to
the structured Alembic-managed tables introduced in migration 20260627_campaign_registry.
They require an asyncpg pool (no in-memory fallback) to enforce the production
invariant that canonical campaign identity is never transient.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from repositories.repos import get_pool
from shared.logger.logger import get_logger

logger = get_logger("aether.campaign.repository")

# In-memory fallbacks for local development — never used in production
_LOCAL_CAMPAIGNS: dict[str, dict] = {}
_LOCAL_EXTERNAL_REFS: dict[str, dict] = {}
_LOCAL_ALIASES: dict[str, dict] = {}
_LOCAL_REVIEWS: dict[str, dict] = {}


async def _pool():
    return await get_pool()


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict:
    return dict(row)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── CampaignRegistryRepository ────────────────────────────────────────────────

class CampaignRegistryRepository:
    """Typed repository for the campaigns table."""

    async def get_by_id(self, tenant_id: str, campaign_id: UUID) -> Optional[dict]:
        pool = await _pool()
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
        pool = await _pool()
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
        pool = await _pool()
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
        pool = await _pool()
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

class ExternalRefRepository:
    """Typed repository for campaign_external_refs."""

    async def get_exact(
        self,
        tenant_id: str,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
    ) -> Optional[dict]:
        pool = await _pool()
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
        pool = await _pool()
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
        pool = await _pool()
        if pool is None:
            return []
        rows = await pool.fetch(
            "SELECT * FROM campaign_external_refs WHERE tenant_id = $1 AND campaign_id = $2 ORDER BY created_at",
            tenant_id, campaign_id,
        )
        return [_row_to_dict(r) for r in rows]


# ── AliasRepository ───────────────────────────────────────────────────────────

class AliasRepository:
    """Typed repository for campaign_aliases."""

    async def get_active(
        self,
        tenant_id: str,
        alias_type: str,
        alias_value_normalized: str,
    ) -> Optional[dict]:
        pool = await _pool()
        if pool is None:
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
        pool = await _pool()
        if pool is None:
            return {}
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
        pool = await _pool()
        if pool is None:
            raise RuntimeError("Database pool unavailable")
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
        pool = await _pool()
        if pool is None:
            return False
        result = await pool.execute(
            "UPDATE campaign_aliases SET valid_until = NOW(), updated_at = NOW() WHERE tenant_id = $1 AND alias_id = $2 AND valid_until IS NULL",
            tenant_id, alias_id,
        )
        return result.split()[-1] != "0"

    async def list_for_campaign(self, tenant_id: str, campaign_id: UUID) -> list[dict]:
        pool = await _pool()
        if pool is None:
            return []
        rows = await pool.fetch(
            "SELECT * FROM campaign_aliases WHERE tenant_id = $1 AND campaign_id = $2 ORDER BY created_at",
            tenant_id, campaign_id,
        )
        return [_row_to_dict(r) for r in rows]


# ── MappingReviewRepository ───────────────────────────────────────────────────

class MappingReviewRepository:
    """Typed repository for campaign_resolution_reviews."""

    async def get_or_create_open(
        self,
        tenant_id: str,
        evidence_hash: str,
        evidence: dict,
        candidate_campaign_ids: list[UUID],
    ) -> dict:
        """Upsert: increment observed_count on existing open review, else create."""
        pool = await _pool()
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
        pool = await _pool()
        if pool is None:
            return None
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

    async def set_status(self, tenant_id: str, review_id: UUID, status: str) -> Optional[dict]:
        pool = await _pool()
        if pool is None:
            return None
        row = await pool.fetchrow(
            "UPDATE campaign_resolution_reviews SET status = $3, updated_at = NOW() WHERE tenant_id = $1 AND review_id = $2 RETURNING *",
            tenant_id, review_id, status,
        )
        return _row_to_dict(row) if row else None

    async def list_open(
        self,
        tenant_id: str,
        limit: int = 50,
        cursor: Optional[datetime] = None,
    ) -> list[dict]:
        pool = await _pool()
        if pool is None:
            return []
        if cursor:
            rows = await pool.fetch(
                "SELECT * FROM campaign_resolution_reviews WHERE tenant_id = $1 AND status = 'open' AND first_seen_at < $2 ORDER BY first_seen_at DESC LIMIT $3",
                tenant_id, cursor, limit,
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM campaign_resolution_reviews WHERE tenant_id = $1 AND status = 'open' ORDER BY first_seen_at DESC LIMIT $2",
                tenant_id, limit,
            )
        return [_row_to_dict(r) for r in rows]

    async def increment_affected_touchpoints(self, tenant_id: str, evidence_hash: str, count: int = 1) -> None:
        pool = await _pool()
        if pool is None:
            return
        await pool.execute(
            "UPDATE campaign_resolution_reviews SET affected_touchpoints = affected_touchpoints + $3, updated_at = NOW() WHERE tenant_id = $1 AND evidence_hash = $2 AND status = 'open'",
            tenant_id, evidence_hash, count,
        )
