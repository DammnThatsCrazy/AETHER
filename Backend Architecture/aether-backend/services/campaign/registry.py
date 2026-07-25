"""Campaign Registry Service.

Single authoritative source for creating, updating, and querying canonical
Aether campaigns. All connectors and ingestion paths must call this service
rather than inventing their own campaign UUIDs or writing provider IDs into
the canonical campaign_id field.
"""

from __future__ import annotations

import logging

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from shared.logger.logger import get_logger, log_event, metrics

from services.campaign.normalization import (
    build_evidence_hash,
    normalize_external_id,
    normalize_platform,
    normalize_utm_value,
    safe_text,
)
from services.campaign.repository import (
    AliasRepository,
    CampaignRegistryRepository,
    ExternalRefRepository,
    MappingReviewRepository,
)

logger = get_logger("aether.campaign.registry")

RESOLVER_VERSION = "1.0"

# Alias types recognized by the resolver
ALIAS_TYPE_UTM_ID = "utm_id"
ALIAS_TYPE_EXTERNAL_CAMPAIGN_ID = "external_campaign_id"
ALIAS_TYPE_UTM_CAMPAIGN = "utm_campaign"
ALIAS_TYPE_CANONICAL_TOKEN = "canonical_token"
ALIAS_TYPE_LANDING_TOKEN = "landing_token"
ALIAS_TYPE_CUSTOM_TRACKING_CODE = "custom_tracking_code"
ALIAS_TYPE_EXTERNAL_CAMPAIGN_NAME = "external_campaign_name"
ALIAS_TYPE_PARTNER_CODE = "partner_code"
ALIAS_TYPE_AFFILIATE_CODE = "affiliate_code"
ALIAS_TYPE_QR_CODE = "qr_code"


class CampaignRegistryService:
    """Authoritative campaign registry operations."""

    def __init__(
        self,
        *,
        campaign_repo: Optional[CampaignRegistryRepository] = None,
        external_ref_repo: Optional[ExternalRefRepository] = None,
        alias_repo: Optional[AliasRepository] = None,
        review_repo: Optional[MappingReviewRepository] = None,
    ) -> None:
        """Construct the service, optionally injecting its repositories.

        Each repository defaults to the process-wide, pool-resolving instance,
        so existing no-argument callers are unaffected. Injection exists because
        the service's behaviour — confidence scoring, alias resolution, review
        queueing — is worth testing against a controlled store rather than only
        against a live pool.
        """
        self._campaigns = campaign_repo or CampaignRegistryRepository()
        self._external_refs = external_ref_repo or ExternalRefRepository()
        self._aliases = alias_repo or AliasRepository()
        self._reviews = review_repo or MappingReviewRepository()

    # ── External campaign upsert ──────────────────────────────────────────────

    async def upsert_external_campaign(
        self,
        tenant_id: str,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
        *,
        external_campaign_name: Optional[str] = None,
        external_status: Optional[str] = None,
        source_connector_id: Optional[str] = None,
        channel: Optional[str] = None,
        raw_metadata: Optional[dict] = None,
    ) -> dict:
        """Atomically register or update an external campaign.

        Returns the canonical campaign record. Concurrent callers are safe:
        ON CONFLICT in the external_refs upsert ensures only one canonical
        campaign UUID is created per (tenant, platform, account, external_id).

        Invariants:
        - The canonical campaign_id is always an Aether UUID.
        - external_campaign_id is stored separately and never written into campaign_id.
        - Provider rename: external_campaign_name is updated; campaign_id is unchanged.
        """
        canonical_platform = normalize_platform(platform) or platform
        ext_id = normalize_external_id(external_campaign_id) or external_campaign_id
        ext_account = normalize_external_id(external_account_id) or external_account_id

        # 1. Look up existing external reference
        existing_ref = await self._external_refs.get_exact(
            tenant_id, canonical_platform, ext_account, ext_id
        )

        if existing_ref:
            # Update mutable provider metadata; UUID is unchanged
            campaign = await self._campaigns.update_metadata(
                tenant_id,
                existing_ref["campaign_id"],
                name=external_campaign_name,
                provider_status=external_status,
                sync_status="synced",
                last_seen_at=datetime.now(timezone.utc),
            )
            await self._external_refs.upsert(
                tenant_id, existing_ref["campaign_id"], canonical_platform,
                ext_account, ext_id,
                external_campaign_name=external_campaign_name,
                external_status=external_status,
                source_connector_id=source_connector_id,
                raw_metadata=raw_metadata,
            )
            metrics.increment("campaign_registry_upsert_total", labels={"origin": "external", "action": "update"})
            return campaign or await self._campaigns.get_by_id_or_fail(tenant_id, existing_ref["campaign_id"])

        # 2. Create canonical campaign then external reference
        name = external_campaign_name or f"{canonical_platform} campaign {ext_id}"
        try:
            campaign = await self._campaigns.create(
                tenant_id, name,
                channel=channel,
                origin="external",
                primary_platform=canonical_platform,
                source_connector_id=source_connector_id,
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
                properties={"source_connector_id": source_connector_id} if source_connector_id else {},
            )
        except Exception as exc:
            # Race condition: another worker created the campaign; re-read it
            log_event(logger, logging.WARNING, "campaign_create_race", error=str(exc), platform=canonical_platform, ext_id=ext_id)
            existing_ref = await self._external_refs.get_exact(
                tenant_id, canonical_platform, ext_account, ext_id
            )
            if existing_ref:
                campaign = await self._campaigns.get_by_id_or_fail(tenant_id, existing_ref["campaign_id"])
                await self._external_refs.upsert(
                    tenant_id, campaign["campaign_id"], canonical_platform, ext_account, ext_id,
                    external_campaign_name=external_campaign_name, external_status=external_status,
                    source_connector_id=source_connector_id, raw_metadata=raw_metadata,
                )
                return campaign
            raise

        campaign_id: UUID = campaign["campaign_id"]

        # 3. Register external reference
        await self._external_refs.upsert(
            tenant_id, campaign_id, canonical_platform, ext_account, ext_id,
            external_campaign_name=external_campaign_name, external_status=external_status,
            source_connector_id=source_connector_id, raw_metadata=raw_metadata,
        )

        # 4. Register authoritative aliases from known provider metadata
        await self._register_external_aliases(
            tenant_id, campaign_id, canonical_platform, ext_account, ext_id,
            external_campaign_name=external_campaign_name,
            source_connector_id=source_connector_id,
        )

        metrics.increment("campaign_registry_upsert_total", labels={"origin": "external", "action": "create"})
        log_event(logger, logging.INFO,
            "campaign_registered",
            tenant_id=tenant_id,
            campaign_id=str(campaign_id),
            platform=canonical_platform,
            external_campaign_id=ext_id,
        )
        return campaign

    async def _register_external_aliases(
        self,
        tenant_id: str,
        campaign_id: UUID,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
        *,
        external_campaign_name: Optional[str] = None,
        source_connector_id: Optional[str] = None,
    ) -> None:
        """Register authoritative platform-scoped aliases after campaign creation."""
        provenance = {"platform": platform, "external_account_id": external_account_id}

        # external_campaign_id alias — scoped to platform+account to avoid collisions
        alias_value_normalized = f"{platform}::{external_account_id}::{normalize_external_id(external_campaign_id)}"
        await self._aliases.create(
            tenant_id, campaign_id,
            ALIAS_TYPE_EXTERNAL_CAMPAIGN_ID,
            external_campaign_id,
            alias_value_normalized,
            platform=platform,
            external_account_id=external_account_id,
            source_connector_id=source_connector_id,
            created_by="system",
            provenance=provenance,
        )
        metrics.increment("campaign_alias_created_total", labels={"alias_type": ALIAS_TYPE_EXTERNAL_CAMPAIGN_ID})

        # Also register as a UTM_CAMPAIGN composite alias so the resolver's composite
        # step can match SDK touchpoints that carry the provider campaign ID in utm_campaign
        # (which tracking templates often do automatically).
        utm_composite_normalized = alias_value_normalized  # same scoped composite key
        await self._aliases.create(
            tenant_id, campaign_id,
            ALIAS_TYPE_UTM_CAMPAIGN,
            external_campaign_id,
            utm_composite_normalized,
            platform=platform,
            external_account_id=external_account_id,
            source_connector_id=source_connector_id,
            created_by="system",
            provenance={**provenance, "auto_utm_alias": True},
        )
        metrics.increment("campaign_alias_created_total", labels={"alias_type": ALIAS_TYPE_UTM_CAMPAIGN})

    # ── Custom campaign creation ──────────────────────────────────────────────

    async def create_custom_campaign(
        self,
        tenant_id: str,
        name: str,
        *,
        channel: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        budget_usd: Optional[Decimal] = None,
        properties: Optional[dict] = None,
        created_by: str = "tenant",
    ) -> dict:
        """Create a manually registered Custom Campaign.

        Custom campaigns are used when no authoritative external campaign source
        exists. They are clearly labeled with origin='custom' and never imply
        that Aether has created an external ad campaign.
        """
        campaign = await self._campaigns.create(
            tenant_id, name,
            channel=channel,
            origin="custom",
            start_at=start_at,
            end_at=end_at,
            budget_usd=budget_usd,
            properties=properties or {},
        )
        metrics.increment("campaign_registry_upsert_total", labels={"origin": "custom", "action": "create"})
        log_event(logger, logging.INFO, "custom_campaign_created", tenant_id=tenant_id, campaign_id=str(campaign["campaign_id"]))
        return campaign

    # ── Alias management ──────────────────────────────────────────────────────

    async def add_alias(
        self,
        tenant_id: str,
        campaign_id: UUID,
        alias_type: str,
        alias_value: str,
        *,
        platform: Optional[str] = None,
        external_account_id: Optional[str] = None,
        source: Optional[str] = None,
        medium: Optional[str] = None,
        source_connector_id: Optional[str] = None,
        created_by: str = "tenant",
        provenance: Optional[dict] = None,
    ) -> Optional[dict]:
        """Add an alias. Returns None if a conflicting active alias already exists."""
        normalized = normalize_utm_value(alias_value)
        if not normalized:
            raise ValueError(f"alias_value cannot be empty after normalization: {alias_value!r}")
        result = await self._aliases.create(
            tenant_id, campaign_id, alias_type, alias_value, normalized,
            platform=platform, external_account_id=external_account_id,
            source=source, medium=medium, source_connector_id=source_connector_id,
            created_by=created_by, provenance=provenance or {},
        )
        if result:
            metrics.increment("campaign_alias_created_total", labels={"alias_type": alias_type})
        else:
            metrics.increment("campaign_alias_conflict_total", labels={"alias_type": alias_type})
        return result

    async def expire_alias(self, tenant_id: str, alias_id: UUID) -> bool:
        return await self._aliases.expire(tenant_id, alias_id)

    # ── Archive ───────────────────────────────────────────────────────────────

    async def archive_external_campaign(
        self,
        tenant_id: str,
        platform: str,
        external_account_id: str,
        external_campaign_id: str,
    ) -> None:
        """Mark an external campaign as archived when the provider deletes or pauses it.

        Historical measurement data is never deleted.
        """
        canonical_platform = normalize_platform(platform) or platform
        ref = await self._external_refs.get_exact(
            tenant_id, canonical_platform, external_account_id, external_campaign_id
        )
        if ref:
            await self._campaigns.update_metadata(
                tenant_id, ref["campaign_id"],
                provider_status="archived",
                archived_at=datetime.now(timezone.utc),
            )
            await self._external_refs.upsert(
                tenant_id, ref["campaign_id"], canonical_platform,
                external_account_id, external_campaign_id,
                external_status="archived",
            )

    # ── Mapping Review ────────────────────────────────────────────────────────

    async def get_or_create_review(
        self,
        tenant_id: str,
        evidence: dict[str, Any],
        candidate_campaign_ids: Optional[list[UUID]] = None,
    ) -> dict:
        """Idempotently create or increment a Mapping Review item."""
        evidence_hash = build_evidence_hash(tenant_id, evidence)
        review = await self._reviews.get_or_create_open(
            tenant_id, evidence_hash, evidence, candidate_campaign_ids or []
        )
        metrics.gauge("campaign_mapping_review_open", 1, labels={"tenant_id": tenant_id})
        return review

    async def resolve_review(
        self,
        tenant_id: str,
        review_id: UUID,
        campaign_id: UUID,
        resolved_by: str,
        note: Optional[str] = None,
    ) -> Optional[dict]:
        # Validate campaign belongs to tenant
        campaign = await self._campaigns.get_by_id(tenant_id, campaign_id)
        if campaign is None:
            raise ValueError(f"campaign {campaign_id} not found for tenant {tenant_id}")
        result = await self._reviews.resolve(tenant_id, review_id, campaign_id, resolved_by, note)
        if result:
            # Create a durable alias from the review evidence so the same evidence
            # resolves deterministically in future without creating another review.
            evidence = result.get("evidence") or {}
            utm_campaign = evidence.get("utm_campaign")
            if utm_campaign:
                normalized = normalize_utm_value(utm_campaign)
                if normalized:
                    await self._aliases.create(
                        tenant_id, campaign_id,
                        ALIAS_TYPE_UTM_CAMPAIGN,
                        utm_campaign,
                        normalized,
                        platform=evidence.get("platform"),
                        external_account_id=evidence.get("external_account_id"),
                        created_by=resolved_by,
                        provenance={"source": "mapping_review_resolution", "review_id": str(review_id)},
                    )
            log_event(logger, logging.INFO, "mapping_review_resolved", tenant_id=tenant_id, review_id=str(review_id), campaign_id=str(campaign_id))
        return result

    async def ignore_review(self, tenant_id: str, review_id: UUID) -> Optional[dict]:
        return await self._reviews.set_status(tenant_id, review_id, "ignored")

    async def reopen_review(self, tenant_id: str, review_id: UUID) -> Optional[dict]:
        return await self._reviews.set_status(tenant_id, review_id, "open")

    async def list_mapping_reviews(
        self, tenant_id: str, limit: int = 50, cursor: Optional[datetime] = None
    ) -> list[dict]:
        return await self._reviews.list_open(tenant_id, limit=limit, cursor=cursor)

    # ── Quality ───────────────────────────────────────────────────────────────

    async def get_mapping_quality(self, tenant_id: str) -> dict:
        """Compute mapping quality metrics for the tenant."""
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is None:
            return {
                "spend_mapping_rate": None,
                "touchpoint_mapping_rate": None,
                "unresolved_reviews": 0,
                "open_reviews": 0,
                "source_count": 0,
            }

        spend_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE campaign_resolution_status = 'resolved'
                    OR campaign_id IS NOT NULL) AS mapped
            FROM spend_records WHERE tenant_id = $1
            """,
            tenant_id,
        )
        touch_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE campaign_resolution_status = 'resolved') AS mapped
            FROM silver_campaign_touchpoint_facts WHERE tenant_id = $1
            """,
            tenant_id,
        )
        review_count = await pool.fetchval(
            "SELECT COUNT(*) FROM campaign_resolution_reviews WHERE tenant_id = $1 AND status = 'open'",
            tenant_id,
        )
        source_count = await pool.fetchval(
            "SELECT COUNT(DISTINCT source_connector_id) FROM campaign_external_refs WHERE tenant_id = $1",
            tenant_id,
        )

        def rate(mapped: int, total: int) -> Optional[float]:
            return round(mapped / total, 4) if total else None

        return {
            "spend_mapping_rate": rate(spend_stats["mapped"] or 0, spend_stats["total"] or 0),
            "touchpoint_mapping_rate": rate(touch_stats["mapped"] or 0, touch_stats["total"] or 0),
            "unresolved_reviews": review_count or 0,
            "open_reviews": review_count or 0,
            "source_count": source_count or 0,
        }
