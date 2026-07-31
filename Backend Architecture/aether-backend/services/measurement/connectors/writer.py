"""CampaignMeasurementWriter — shared registry-aware spend writer.

All measurement connectors must use this writer to ensure:
  1. External campaigns are registered in the Campaign Registry before spend is written.
  2. spend_records.campaign_id always contains a canonical Aether UUID.
  3. External provider IDs are preserved separately in external_campaign_id.
  4. Connector cursor state is only updated after durable writes succeed.

ExternalCampaignMetric is the normalized provider-agnostic result contract.
Every connector converts its API response to this format before calling write_metrics().
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from shared.logger.logger import get_logger, log_event, metrics

from services.campaign.registry import CampaignRegistryService
from services.measurement.repositories.spend_repo import SpendRepository

logger = get_logger("aether.measurement.connectors.writer")

WRITER_VERSION = "1.0"


@dataclass
class ExternalCampaignMetric:
    """Normalized provider-agnostic campaign metric for a single period/day."""
    platform: str
    external_account_id: str
    external_campaign_id: str
    period_start: datetime
    period_end: datetime
    source_timezone: str = "UTC"
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    spend: Decimal = Decimal("0")
    currency: str = "USD"
    # Optional extended dimensions
    external_campaign_name: Optional[str] = None
    external_status: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_set_id: Optional[str] = None
    ad_id: Optional[str] = None
    placement: Optional[str] = None
    keyword: Optional[str] = None
    engagements: int = 0
    video_views: int = 0
    viewable_impressions: int = 0
    frequency: float = 0.0
    # Idempotency
    source_record_id: Optional[str] = None
    provider_updated_at: Optional[datetime] = None
    # Provider raw data preserved for audit
    raw_dimensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class WriteResult:
    spend_records_written: int = 0
    campaigns_registered: int = 0
    campaigns_updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class CampaignMeasurementWriter:
    """Registry-aware writer that ensures spend facts use canonical campaign UUIDs.

    Write order:
      1. upsert_external_campaign() → canonical UUID
      2. write spend_record with canonical campaign_id + external_campaign_id
      3. cursor update happens externally after this method returns successfully
    """

    def __init__(
        self,
        registry_service: Optional[CampaignRegistryService] = None,
        spend_repo: Optional[SpendRepository] = None,
    ) -> None:
        self._registry = registry_service or CampaignRegistryService()
        self._spend_repo = spend_repo or SpendRepository()

    async def write_metrics(
        self,
        tenant_id: str,
        connector_id: str,
        metrics_list: list[ExternalCampaignMetric],
        *,
        make_idem_key_fn: Optional[Any] = None,
    ) -> WriteResult:
        """Write a batch of external campaign metrics to canonical spend facts.

        Args:
            tenant_id: Authenticated tenant scope.
            connector_id: Source connector identifier.
            metrics_list: Normalized metric rows from the connector.
            make_idem_key_fn: Optional callable(metric) → str for idempotency.
        """
        result = WriteResult()

        # Step 1: Register all unique campaigns first (batch deduplication)
        external_to_canonical: dict[tuple[str, str, str], UUID] = {}

        unique_campaigns: dict[tuple[str, str, str], ExternalCampaignMetric] = {}
        for m in metrics_list:
            key = (m.platform, m.external_account_id, m.external_campaign_id)
            unique_campaigns[key] = m

        for (platform, account_id, campaign_id_str), m in unique_campaigns.items():
            try:
                campaign = await self._registry.upsert_external_campaign(
                    tenant_id,
                    platform,
                    account_id,
                    campaign_id_str,
                    external_campaign_name=m.external_campaign_name,
                    external_status=m.external_status,
                    source_connector_id=connector_id,
                    raw_metadata=m.raw_dimensions,
                )
                canonical_uuid: UUID = campaign["campaign_id"]
                external_to_canonical[(platform, account_id, campaign_id_str)] = canonical_uuid
                result.campaigns_registered += 1
            except Exception as exc:
                error_msg = f"Failed to register campaign {campaign_id_str} on {platform}: {exc}"
                log_event(logger, logging.ERROR, "campaign_registration_failed", error=error_msg, tenant_id=tenant_id)
                result.errors.append(error_msg)

        # Step 2: Write spend records with canonical campaign_id + external fields
        for m in metrics_list:
            key = (m.platform, m.external_account_id, m.external_campaign_id)
            canonical_uuid = external_to_canonical.get(key)
            if canonical_uuid is None:
                result.errors.append(f"No canonical UUID for {key}; spend record skipped")
                continue

            if make_idem_key_fn:
                idem_key = make_idem_key_fn(m)
            else:
                import hashlib
                idem_key = hashlib.sha256(
                    f"{tenant_id}:{m.platform}:{m.external_account_id}:{m.external_campaign_id}:{m.period_start.isoformat()}".encode()
                ).hexdigest()

            try:
                await self._spend_repo.upsert({
                    "tenant_id": tenant_id,
                    "platform": m.platform,
                    "ad_account_id": m.external_account_id,
                    # Canonical Aether UUID — never a provider ID
                    "campaign_id": str(canonical_uuid),
                    # Provider identity preserved separately
                    "external_campaign_id": m.external_campaign_id,
                    "external_account_id": m.external_account_id,
                    "campaign_resolution_status": "resolved",
                    "campaign_resolution_method": "exact_external_ref",
                    "campaign_resolution_version": WRITER_VERSION,
                    # Dimensions
                    "period_start": m.period_start.isoformat(),
                    "period_end": m.period_end.isoformat(),
                    "billing_currency": m.currency,
                    "normalized_currency": "USD",
                    "impressions": m.impressions,
                    "clicks": m.clicks,
                    "media_spend": str(m.spend),
                    "total_cost": str(m.spend),
                    "source_record_id": m.source_record_id or idem_key,
                    "source_connector_id": connector_id,
                    "idempotency_key": idem_key,
                })
                result.spend_records_written += 1
            except Exception as exc:
                error_msg = f"Failed to write spend for campaign {m.external_campaign_id}: {exc}"
                log_event(logger, logging.ERROR, "spend_write_failed", error=error_msg, tenant_id=tenant_id)
                result.errors.append(error_msg)

        metrics.increment(
            "campaign_source_sync_total",
            tags={"platform": metrics_list[0].platform if metrics_list else "unknown",
                  "status": "success" if result.success else "partial_failure"},
        )
        log_event(logger, logging.INFO,
            "campaign_metrics_written",
            tenant_id=tenant_id,
            connector_id=connector_id,
            spend_written=result.spend_records_written,
            campaigns_registered=result.campaigns_registered,
            errors=len(result.errors),
        )
        return result
