"""
Aether Backend — Data Lake Repositories (Bronze / Silver / Gold)

Medallion architecture for data persistence with source-tag auditing,
replay/backfill support, and rollback capabilities.

Bronze: Immutable raw provider data with full payload preservation
Silver: Validated, deduplicated, entity-normalized records
Gold: Business metrics, ML features, intelligence highlights

All tiers use the same BaseRepository pattern (asyncpg in prod, in-memory local).

Provenance policy:
- Every Bronze record carries provenance_status, license_status, and quarantine_status.
- Records without a valid license are automatically quarantined.
- Quarantined records are blocked from Silver promotion.
- Gold records carry a lineage_id linking back to their Bronze source manifests.
"""

from __future__ import annotations

import hashlib
import uuid
from enum import Enum
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.lake")


async def _tenant_scoped_find(
    repo: BaseRepository,
    base_filters: dict,
    tenant_id: Optional[str],
    *,
    limit: int,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[dict]:
    """Tenant-scoped lake read: a tenant's own rows PLUS global tenant-less rows,
    never another tenant's rows.

    The lake tiers are written with mixed tenancy — some records carry a real
    ``tenant_id`` (SDK ingestion, card-linked, explicit Gold materialization)
    while others are global/tenant-less (feature ETL, on-chain observations).
    A tenant-facing read must therefore see its own rows and the global rows,
    but not another tenant's. Primary (``tenant_id = X``) and legacy
    (``tenant_id IS NULL OR ''``) result sets are disjoint by construction, so
    they are simply concatenated (tenant first) and capped.

    ``tenant_id=None`` is an explicit, auditable cross-tenant read reserved for
    ETL / global-materialization jobs that have no single owning tenant. An
    empty-string ``tenant_id`` means "no owning tenant" and returns ONLY the
    global/legacy rows — never every tenant's rows (that would be the leak this
    scoping exists to prevent).
    """
    if tenant_id is None:
        return await repo.find_many(
            filters=base_filters, limit=limit, sort_by=sort_by, sort_order=sort_order
        )
    if tenant_id == "":
        # No owning tenant → global/legacy rows only (tenant IS NULL or '').
        return await repo.find_many(
            filters={**base_filters, "tenant_id": ""},
            limit=limit, sort_by=sort_by, sort_order=sort_order,
        )
    primary = await repo.find_many(
        filters={**base_filters, "tenant_id": tenant_id},
        limit=limit, sort_by=sort_by, sort_order=sort_order,
    )
    legacy = await repo.find_many(
        filters={**base_filters, "tenant_id": ""},
        limit=limit, sort_by=sort_by, sort_order=sort_order,
    )
    return (primary + legacy)[:limit]


# ═══════════════════════════════════════════════════════════════════════════
# PROVENANCE ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class ProvenanceStatus(str, Enum):
    VALID = "valid"
    MISSING_LICENSE = "missing_license"
    MISSING_TERMS_REVIEW = "missing_terms_review"
    MISSING_COMMERCIAL_USE_REVIEW = "missing_commercial_use_review"
    MISSING_MODEL_TRAINING_REVIEW = "missing_model_training_review"
    MISSING_SOURCE_ID = "missing_source_id"
    UNVERIFIED = "unverified"
    QUARANTINED = "quarantined"
    REVOKED = "revoked"
    DISABLED = "disabled"


def _compute_provenance_status(
    license_status: str,
    terms_status: str,
    provider_record_id: str,
) -> ProvenanceStatus:
    """Derive provenance status. Fail-conservative — any gap → quarantine."""
    if not provider_record_id:
        return ProvenanceStatus.MISSING_SOURCE_ID
    if license_status in ("unknown", "missing", "pending_review"):
        return ProvenanceStatus.MISSING_LICENSE
    if terms_status in ("unknown", "missing", "pending_review"):
        return ProvenanceStatus.MISSING_TERMS_REVIEW
    _CLEAR_LICENSE_STATUSES = {"valid", "public_api", "open_license", "enterprise_contract"}
    _CLEAR_TERMS_STATUSES = {"approved", "public_api", "open_license", "enterprise_contract", "valid"}
    if license_status in _CLEAR_LICENSE_STATUSES and terms_status in _CLEAR_TERMS_STATUSES:
        return ProvenanceStatus.VALID
    return ProvenanceStatus.UNVERIFIED


def _compute_quarantine_status(provenance_status: ProvenanceStatus, license_status: str) -> str:
    """Quarantine if provenance is not VALID or license is missing/unknown."""
    if provenance_status != ProvenanceStatus.VALID:
        return "quarantined"
    if license_status in ("unknown", "missing", "pending_review"):
        return "quarantined"
    return "not_quarantined"


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
    tenant_id: str = "",
    # Provenance fields
    provenance_status: str = ProvenanceStatus.UNVERIFIED.value,
    license_status: str = "unknown",
    terms_status: str = "unknown",
    commercial_use_status: str = "unknown",
    model_training_status: str = "unknown",
    olympus_owned_source: bool = False,
    source_manifest_id: Optional[str] = None,
    sensitivity_classification: str = "unclassified",
) -> dict:
    """Create a canonical raw record with required audit fields and provenance envelope."""
    now = utc_now().isoformat()
    # tenant_id is included so two tenants with the same provider_record_id
    # are never considered duplicates.
    idempotency_key = hashlib.sha256(
        f"{tenant_id}:{source}:{provider_record_id}:{schema_version}".encode()
    ).hexdigest()[:32]

    raw_payload_hash = hashlib.sha256(
        str(payload).encode()
    ).hexdigest()

    # Derive provenance from provided statuses
    prov_status = ProvenanceStatus(provenance_status) if provenance_status in ProvenanceStatus._value2member_map_ else ProvenanceStatus.UNVERIFIED
    if prov_status == ProvenanceStatus.UNVERIFIED:
        prov_status = _compute_provenance_status(license_status, terms_status, provider_record_id)

    quarantine_status = _compute_quarantine_status(prov_status, license_status)

    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "source_tag": source_tag,
        "provider_record_id": provider_record_id,
        "schema_version": schema_version,
        "idempotency_key": idempotency_key,
        "entity_id": entity_id or "",
        "entity_type": entity_type or "",
        "tenant_id": tenant_id,
        "payload": payload,
        "ingested_at": now,
        "created_at": now,
        "updated_at": now,
        # Provenance envelope
        "provenance_status": prov_status.value,
        "license_status": license_status,
        "terms_status": terms_status,
        "commercial_use_status": commercial_use_status,
        "model_training_status": model_training_status,
        "olympus_owned_source": olympus_owned_source,
        "source_manifest_id": source_manifest_id or "",
        "raw_payload_hash": raw_payload_hash,
        "sensitivity_classification": sensitivity_classification,
        "quarantine_status": quarantine_status,
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
        # Provenance fields
        provenance_status: str = ProvenanceStatus.UNVERIFIED.value,
        license_status: str = "unknown",
        terms_status: str = "unknown",
        commercial_use_status: str = "unknown",
        model_training_status: str = "unknown",
        olympus_owned_source: bool = False,
        source_manifest_id: Optional[str] = None,
        sensitivity_classification: str = "unclassified",
    ) -> tuple[dict, bool]:
        """Ingest a raw record. Idempotent — skips duplicates.

        Provenance is computed from license_status and terms_status.
        Records with missing license are automatically quarantined and
        blocked from Silver promotion.

        Returns (record, is_new) where is_new is True for fresh inserts and
        False when the record already existed (duplicate).
        """
        record = make_raw_record(
            source=source,
            source_tag=source_tag,
            provider_record_id=provider_record_id,
            payload=payload,
            schema_version=schema_version,
            entity_id=entity_id,
            entity_type=entity_type,
            tenant_id=tenant_id,
            provenance_status=provenance_status,
            license_status=license_status,
            terms_status=terms_status,
            commercial_use_status=commercial_use_status,
            model_training_status=model_training_status,
            olympus_owned_source=olympus_owned_source,
            source_manifest_id=source_manifest_id,
            sensitivity_classification=sensitivity_classification,
        )

        if record.get("quarantine_status") == "quarantined":
            metrics.increment("lake_bronze_quarantined", labels={"source": source})
            logger.warning(
                f"Bronze record quarantined: source={source} "
                f"provenance={record.get('provenance_status')} "
                f"license={license_status}"
            )

        # Idempotency check — always scoped by tenant_id to prevent cross-tenant collision
        existing = await self.find_many(
            filters={"idempotency_key": record["idempotency_key"], "tenant_id": tenant_id}, limit=1
        )
        if existing:
            metrics.increment("lake_bronze_dedup", labels={"source": source})
            return existing[0], False

        result = await self.insert(record["id"], record)
        metrics.increment("lake_bronze_ingested", labels={"source": source})
        logger.info(f"Bronze ingested: source={source} tag={source_tag} id={provider_record_id}")
        return result, True

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
            _, is_new = await self.ingest(
                source=source,
                source_tag=source_tag,
                provider_record_id=rec.get("id", str(uuid.uuid4())),
                payload=rec,
                entity_id=rec.get("entity_id", ""),
                entity_type=rec.get("entity_type", ""),
                tenant_id=tenant_id,
            )
            if is_new:
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

    @staticmethod
    def check_promotion_eligibility(bronze_record: dict) -> tuple[bool, str]:
        """Check if a Bronze record is eligible for Silver promotion.

        Blocks promotion if:
        - quarantine_status == "quarantined"
        - provenance_status not in {valid}

        Returns (eligible, reason).
        """
        quarantine = bronze_record.get("quarantine_status", "quarantined")
        if quarantine == "quarantined":
            prov = bronze_record.get("provenance_status", "unverified")
            return False, f"quarantined_bronze_blocked_silver_promotion provenance={prov}"

        prov_status = bronze_record.get("provenance_status", "unverified")
        if prov_status != ProvenanceStatus.VALID.value:
            return False, f"provenance_not_valid provenance={prov_status}"

        return True, "eligible"

    async def upsert_record(
        self,
        entity_id: str,
        entity_type: str,
        source: str,
        source_tag: str,
        normalized: dict,
        bronze_id: str = "",
        tenant_id: str = "",
        bronze_record: Optional[dict] = None,
    ) -> dict:
        """Upsert a normalized record. Merges with existing entity data.

        Silver promotion is blocked if the originating Bronze record is quarantined
        or has invalid provenance. Pass bronze_record to enforce this gate.
        """
        if bronze_record is not None:
            eligible, reason = self.check_promotion_eligibility(bronze_record)
            if not eligible:
                metrics.increment("lake_silver_promotion_blocked", labels={"source": source})
                raise ValueError(f"Silver promotion blocked: {reason}")

        record_id = hashlib.sha256(f"{tenant_id}:{entity_type}:{entity_id}:{source}".encode()).hexdigest()[:24]

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

    async def get_entity(
        self, entity_id: str, entity_type: str, *, tenant_id: Optional[str]
    ) -> list[dict]:
        """Get Silver records for an entity, scoped to a tenant.

        Pass the caller's ``tenant_id`` to return that tenant's rows plus global
        tenant-less rows (never another tenant's). Pass ``tenant_id=None`` ONLY
        for cross-tenant ETL/graph jobs — an explicit, auditable opt-out. The
        keyword is required (no default) so a caller can never silently omit it.
        """
        return await _tenant_scoped_find(
            self, {"entity_id": entity_id, "entity_type": entity_type},
            tenant_id, limit=100,
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
        lineage_id: Optional[str] = None,
        source_manifest_ids: Optional[list] = None,
        model_training_eligible: bool = False,
    ) -> dict:
        """Materialize a metric/feature/highlight into Gold.

        lineage_id links this Gold record back to its Bronze source manifests
        and data rights grants for audit, revocation, and compliance.
        """
        # tenant_id is part of the identity: without it, two tenants
        # materializing the same metric for the same entity collide on one
        # record_id and silently overwrite each other's Gold value. Mirrors the
        # Silver record_id, which already includes tenant_id. (See
        # compute_record_id() below for a pure, reusable version of this exact
        # formula — e.g. scripts/gold_tenant_backfill.py rekeys rows written
        # under the pre-fix tenant-less formula by calling it directly instead
        # of forking the hash.)
        record_id = hashlib.sha256(
            f"{tenant_id}:{metric_name}:{entity_id}:{entity_type}".encode()
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
            "lineage_id": lineage_id or "",
            "source_manifest_ids": source_manifest_ids or [],
            "model_training_eligible": model_training_eligible,
        }

        existing = await self.find_by_id(record_id)
        if existing:
            result = await self.update(record_id, data)
            metrics.increment("lake_gold_updated", labels={"metric": metric_name})
        else:
            result = await self.insert(record_id, data)
            metrics.increment("lake_gold_created", labels={"metric": metric_name})

        return result

    @staticmethod
    def compute_record_id(tenant_id: str, metric_name: str, entity_id: str, entity_type: str) -> str:
        """Compute the tenant-inclusive Gold ``record_id`` — the exact formula
        ``materialize()`` hashes inline above, exposed as a pure, side-effect-free
        function.

        This does not change ``materialize()``'s behavior; it is purely additive.
        It exists so a caller that needs to know a row's canonical key WITHOUT
        writing (e.g. ``scripts/gold_tenant_backfill.py``, deciding whether an
        existing row is already correctly keyed before touching it) can reuse the
        real hash instead of reimplementing/forking it.
        """
        return hashlib.sha256(
            f"{tenant_id}:{metric_name}:{entity_id}:{entity_type}".encode()
        ).hexdigest()[:24]

    async def get_metrics(
        self,
        entity_id: str,
        entity_type: str = "",
        metric_name: str = "",
        *,
        tenant_id: Optional[str],
    ) -> list[dict]:
        """Query Gold metrics for an entity, scoped to a tenant.

        Returns the tenant's rows plus global tenant-less rows (never another
        tenant's). ``tenant_id=None`` is an explicit cross-tenant read for ETL.
        The keyword is required so a caller can never silently omit tenant scope.
        """
        filters: dict = {"entity_id": entity_id}
        if entity_type:
            filters["entity_type"] = entity_type
        if metric_name:
            filters["metric_name"] = metric_name
        return await _tenant_scoped_find(self, filters, tenant_id, limit=200)

    async def get_highlights(
        self, metric_name: str, limit: int = 50, *, tenant_id: Optional[str]
    ) -> list[dict]:
        """Get top highlights for a metric (e.g., top wallet risk scores).

        Scoped to a tenant's rows plus global tenant-less rows.
        ``tenant_id=None`` is an explicit cross-tenant read for ETL.
        """
        return await _tenant_scoped_find(
            self, {"metric_name": metric_name}, tenant_id,
            limit=limit, sort_by="updated_at", sort_order="desc",
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

# Intelligence surface repos — consumed by Profile 360 intelligence extension endpoints.
# These are populated by external ETL pipelines (Moralis, CoinGecko, DeFiLlama, Snapshot,
# Plaid, etc.) via GoldRepository.materialize().  The BaseRepository pattern means they
# operate in-memory during local/test runs and against asyncpg in production.
gold_entity_tiers = GoldRepository("entity_tiers")
gold_asset_composition = GoldRepository("asset_composition")
gold_entity_pnl = GoldRepository("entity_pnl")
gold_trading_profile = GoldRepository("trading_profile")
gold_location_history = GoldRepository("location_history")
gold_temporal_heatmap = GoldRepository("temporal_heatmap")
gold_social_intelligence = GoldRepository("social_intelligence")
gold_journey_economics = GoldRepository("journey_economics")
gold_ad_spend = GoldRepository("ad_spend")
gold_credit_signals = GoldRepository("credit_signals")
gold_tradfi_portfolio = GoldRepository("tradfi_portfolio")
gold_web3_daily_metrics = GoldRepository("web3_daily_metrics")

# Connector events — Bronze-only; connector sync events land here before flowing
# to the intelligence workers (no Silver/Gold tier; same consumer path as sdk_events).
bronze_connectors = BronzeRepository("connector_events")
