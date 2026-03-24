"""
Aether Backend — Data Lake Repositories (Bronze / Silver / Gold)

Medallion architecture for data persistence with source-tag auditing,
replay/backfill support, and rollback capabilities.

Bronze: Immutable raw provider data with full payload preservation
Silver: Validated, deduplicated, entity-normalized records
Gold: Business metrics, ML features, intelligence highlights

All tiers use the same BaseRepository pattern (asyncpg in prod, in-memory local).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository, get_pool
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.lake")


# ═══════════════════════════════════════════════════════════════════════════
# CANONICAL RAW RECORD SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

def make_raw_record(
    source: str,
    source_tag: str,
    provider_record_id: str,
    payload: dict,
    schema_version: str = "1.0",
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
) -> dict:
    """Create a canonical raw record with required audit fields."""
    now = utc_now().isoformat()
    idempotency_key = hashlib.sha256(
        f"{source}:{provider_record_id}:{schema_version}".encode()
    ).hexdigest()[:32]
    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "source_tag": source_tag,
        "provider_record_id": provider_record_id,
        "schema_version": schema_version,
        "idempotency_key": idempotency_key,
        "entity_id": entity_id or "",
        "entity_type": entity_type or "",
        "payload": payload,
        "ingested_at": now,
        "created_at": now,
        "updated_at": now,
    }


# ═══════════════════════════════════════════════════════════════════════════
# BRONZE — Immutable Raw Persistence
# ═══════════════════════════════════════════════════════════════════════════

class BronzeRepository(BaseRepository):
    """
    Bronze tier: immutable raw data from all providers.
    Every record has source, source_tag, provider_record_id, and full payload.
    Supports replay via idempotency keys and rollback via source_tag.
    """

    def __init__(self, domain: str = "default") -> None:
        super().__init__(f"bronze_{domain}")
        self._domain = domain

    async def ingest(
        self,
        source: str,
        source_tag: str,
        provider_record_id: str,
        payload: dict,
        schema_version: str = "1.0",
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        tenant_id: str = "",
    ) -> dict:
        """Ingest a raw record. Idempotent — skips duplicates."""
        record = make_raw_record(
            source=source,
            source_tag=source_tag,
            provider_record_id=provider_record_id,
            payload=payload,
            schema_version=schema_version,
            entity_id=entity_id,
            entity_type=entity_type,
        )
        record["tenant_id"] = tenant_id

        # Idempotency check
        existing = await self.find_many(
            filters={"idempotency_key": record["idempotency_key"]}, limit=1
        )
        if existing:
            metrics.increment("lake_bronze_dedup", labels={"source": source})
            return existing[0]

        result = await self.insert(record["id"], record)
        metrics.increment("lake_bronze_ingested", labels={"source": source})
        logger.info(f"Bronze ingested: source={source} tag={source_tag} id={provider_record_id}")
        return result

    async def ingest_batch(
        self,
        records: list[dict],
        source: str,
        source_tag: str,
        tenant_id: str = "",
    ) -> int:
        """Batch ingest. Returns count of new records (excludes duplicates)."""
        count = 0
        for rec in records:
            result = await self.ingest(
                source=source,
                source_tag=source_tag,
                provider_record_id=rec.get("id", str(uuid.uuid4())),
                payload=rec,
                entity_id=rec.get("entity_id", ""),
                entity_type=rec.get("entity_type", ""),
                tenant_id=tenant_id,
            )
            if result.get("created_at") == result.get("ingested_at"):
                count += 1
        return count

    async def query_by_source_tag(self, source_tag: str, limit: int = 100) -> list[dict]:
        """Query raw records by source_tag for audit/rollback."""
        return await self.find_many(filters={"source_tag": source_tag}, limit=limit)

    async def rollback_by_source_tag(self, source_tag: str) -> int:
        """Delete all records matching a source_tag. Returns count deleted."""
        records = await self.query_by_source_tag(source_tag, limit=10000)
        count = 0
        for rec in records:
            if await self.delete(rec["id"]):
                count += 1
        if count > 0:
            logger.warning(f"Bronze rollback: source_tag={source_tag} deleted={count}")
            metrics.increment("lake_bronze_rollback", labels={"source_tag": source_tag})
        return count


# ═══════════════════════════════════════════════════════════════════════════
# SILVER — Validated, Deduplicated, Normalized
# ═══════════════════════════════════════════════════════════════════════════

class SilverRepository(BaseRepository):
    """
    Silver tier: validated, typed, deduplicated, entity-normalized records.
    Produced deterministically from Bronze inputs.
    """

    def __init__(self, domain: str = "default") -> None:
        super().__init__(f"silver_{domain}")
        self._domain = domain

    async def upsert_record(
        self,
        entity_id: str,
        entity_type: str,
        source: str,
        source_tag: str,
        normalized: dict,
        bronze_id: str = "",
        tenant_id: str = "",
    ) -> dict:
        """Upsert a normalized record. Merges with existing entity data."""
        record_id = hashlib.sha256(f"{entity_type}:{entity_id}:{source}".encode()).hexdigest()[:24]

        existing = await self.find_by_id(record_id)
        if existing:
            # Merge: new data overwrites but preserves existing fields
            merged = {**existing, **normalized}
            merged["updated_at"] = utc_now().isoformat()
            merged["source_tag"] = source_tag
            merged["bronze_id"] = bronze_id
            result = await self.update(record_id, merged)
            metrics.increment("lake_silver_updated", labels={"entity_type": entity_type})
        else:
            data = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "source": source,
                "source_tag": source_tag,
                "bronze_id": bronze_id,
                "tenant_id": tenant_id,
                **normalized,
            }
            result = await self.insert(record_id, data)
            metrics.increment("lake_silver_created", labels={"entity_type": entity_type})

        return result

    async def get_entity(self, entity_id: str, entity_type: str) -> list[dict]:
        """Get all Silver records for an entity across sources."""
        return await self.find_many(
            filters={"entity_id": entity_id, "entity_type": entity_type}, limit=100
        )

    async def rollback_by_source_tag(self, source_tag: str) -> int:
        """Delete all Silver records matching a source_tag."""
        records = await self.find_many(filters={"source_tag": source_tag}, limit=10000)
        count = 0
        for rec in records:
            if await self.delete(rec["id"]):
                count += 1
        if count > 0:
            logger.warning(f"Silver rollback: source_tag={source_tag} deleted={count}")
        return count


# ═══════════════════════════════════════════════════════════════════════════
# GOLD — Business Metrics, Features, Highlights
# ═══════════════════════════════════════════════════════════════════════════

class GoldRepository(BaseRepository):
    """
    Gold tier: business metrics, ML-ready features, intelligence highlights.
    Consumed by ML training, graph mutations, and intelligence APIs.
    """

    def __init__(self, domain: str = "default") -> None:
        super().__init__(f"gold_{domain}")
        self._domain = domain

    async def materialize(
        self,
        metric_name: str,
        entity_id: str,
        entity_type: str,
        value: Any,
        dimensions: Optional[dict] = None,
        source_tag: str = "",
        tenant_id: str = "",
    ) -> dict:
        """Materialize a metric/feature/highlight into Gold."""
        record_id = hashlib.sha256(
            f"{metric_name}:{entity_id}:{entity_type}".encode()
        ).hexdigest()[:24]

        data = {
            "metric_name": metric_name,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "value": value,
            "dimensions": dimensions or {},
            "source_tag": source_tag,
            "tenant_id": tenant_id,
            "materialized_at": utc_now().isoformat(),
        }

        existing = await self.find_by_id(record_id)
        if existing:
            result = await self.update(record_id, data)
            metrics.increment("lake_gold_updated", labels={"metric": metric_name})
        else:
            result = await self.insert(record_id, data)
            metrics.increment("lake_gold_created", labels={"metric": metric_name})

        return result

    async def get_metrics(
        self,
        entity_id: str,
        entity_type: str = "",
        metric_name: str = "",
    ) -> list[dict]:
        """Query Gold metrics for an entity."""
        filters: dict = {"entity_id": entity_id}
        if entity_type:
            filters["entity_type"] = entity_type
        if metric_name:
            filters["metric_name"] = metric_name
        return await self.find_many(filters=filters, limit=200)

    async def get_highlights(self, metric_name: str, limit: int = 50) -> list[dict]:
        """Get top highlights for a metric (e.g., top wallet risk scores)."""
        return await self.find_many(
            filters={"metric_name": metric_name},
            limit=limit,
            sort_by="updated_at",
            sort_order="desc",
        )


# ═══════════════════════════════════════════════════════════════════════════
# QUALITY CHECKS
# ═══════════════════════════════════════════════════════════════════════════

async def run_quality_checks(repo: BaseRepository, domain: str = "") -> dict:
    """Run data quality checks on a repository tier."""
    total = await repo.count()
    nulls = await repo.count(filters={"entity_id": ""})
    return {
        "domain": domain or repo.table_name,
        "total_records": total,
        "null_entity_count": nulls,
        "null_rate": round(nulls / max(total, 1), 4),
        "status": "healthy" if nulls / max(total, 1) < 0.05 else "degraded",
        "checked_at": utc_now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE: Domain-specific lake instances
# ═══════════════════════════════════════════════════════════════════════════

# Market data
bronze_market = BronzeRepository("market")
silver_market = SilverRepository("market")
gold_market = GoldRepository("market")

# On-chain data
bronze_onchain = BronzeRepository("onchain")
silver_onchain = SilverRepository("onchain")
gold_onchain = GoldRepository("onchain")

# Social data
bronze_social = BronzeRepository("social")
silver_social = SilverRepository("social")
gold_social = GoldRepository("social")

# Identity / enrichment
bronze_identity = BronzeRepository("identity")
silver_identity = SilverRepository("identity")
gold_identity = GoldRepository("identity")

# Governance
bronze_governance = BronzeRepository("governance")
silver_governance = SilverRepository("governance")
gold_governance = GoldRepository("governance")

# TradFi
bronze_tradfi = BronzeRepository("tradfi")
silver_tradfi = SilverRepository("tradfi")
gold_tradfi = GoldRepository("tradfi")
