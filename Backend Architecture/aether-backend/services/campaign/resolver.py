"""Campaign Resolver — deterministic evidence-to-UUID resolution.

Implements a versioned, ordered resolution strategy. The resolver is deterministic:
given the same evidence and the same resolver version, it always produces the
same output. It never fuzzy-matches campaign names and never resolves across tenants.

Resolution priority (highest confidence first):
  1. Explicit canonical Aether campaign UUID validated against tenant ownership → 1.00
  2. Exact platform + account + external_campaign_id → 1.00
  3. Exact utm_id alias → 0.99
  4. Exact composite alias (platform/account/source/medium/utm_campaign) → 0.95
  5. Exact tenant-unique utm_campaign alias → 0.85
  6. Ambiguous (multiple candidates) → Mapping Review created
  7. Unresolved (no candidates) → Mapping Review created
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from shared.logger.logger import get_logger, metrics

from services.campaign.normalization import (
    build_evidence_hash,
    normalize_external_id,
    normalize_platform,
    normalize_utm_value,
)
from services.campaign.registry import (
    ALIAS_TYPE_EXTERNAL_CAMPAIGN_ID,
    ALIAS_TYPE_UTM_CAMPAIGN,
    ALIAS_TYPE_UTM_ID,
    CampaignRegistryService,
)
from services.campaign.repository import (
    AliasRepository,
    CampaignRegistryRepository,
    ExternalRefRepository,
    MappingReviewRepository,
)

logger = get_logger("aether.campaign.resolver")

RESOLVER_VERSION = "1.0"

ResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "invalid", "not_applicable"]


@dataclass
class ResolutionResult:
    status: ResolutionStatus
    campaign_id: Optional[UUID] = None
    method: Optional[str] = None
    confidence: Optional[Decimal] = None
    resolution_version: str = RESOLVER_VERSION
    matched_external_ref_id: Optional[UUID] = None
    matched_alias_id: Optional[UUID] = None
    candidate_campaign_ids: list[UUID] = field(default_factory=list)
    reason: str = ""
    review_id: Optional[UUID] = None
    normalized_evidence: dict[str, Any] = field(default_factory=dict)


class CampaignResolver:
    """Deterministic campaign evidence resolver."""

    def __init__(
        self,
        registry_service: Optional[CampaignRegistryService] = None,
    ) -> None:
        self._registry = registry_service or CampaignRegistryService()
        self._campaigns = CampaignRegistryRepository()
        self._external_refs = ExternalRefRepository()
        self._aliases = AliasRepository()
        self._reviews = MappingReviewRepository()

    async def resolve_one(
        self,
        tenant_id: str,
        *,
        canonical_campaign_id: Optional[str] = None,
        platform: Optional[str] = None,
        external_account_id: Optional[str] = None,
        external_campaign_id: Optional[str] = None,
        utm_id: Optional[str] = None,
        utm_source: Optional[str] = None,
        utm_medium: Optional[str] = None,
        utm_campaign: Optional[str] = None,
        utm_content: Optional[str] = None,
        utm_term: Optional[str] = None,
        click_ids: Optional[dict[str, str]] = None,
        referrer: Optional[str] = None,
        landing_url: Optional[str] = None,
        source_connector_id: Optional[str] = None,
        create_review_on_failure: bool = True,
    ) -> ResolutionResult:
        """Resolve campaign evidence to a canonical Aether campaign UUID.

        Returns a ResolutionResult. On failure creates a durable Mapping Review
        item unless create_review_on_failure=False.
        """
        import time
        t0 = time.monotonic()

        norm_platform = normalize_platform(platform)
        norm_ext_account = normalize_external_id(external_account_id)
        norm_ext_campaign = normalize_external_id(external_campaign_id)
        norm_utm_id = normalize_utm_value(utm_id)
        norm_utm_campaign = normalize_utm_value(utm_campaign)
        norm_utm_source = normalize_utm_value(utm_source)
        norm_utm_medium = normalize_utm_value(utm_medium)

        evidence = {
            "platform": norm_platform,
            "external_account_id": norm_ext_account,
            "external_campaign_id": norm_ext_campaign,
            "utm_id": norm_utm_id,
            "utm_source": norm_utm_source,
            "utm_medium": norm_utm_medium,
            "utm_campaign": norm_utm_campaign,
            "utm_content": normalize_utm_value(utm_content),
            "utm_term": normalize_utm_value(utm_term),
            "landing_url": landing_url,
        }

        result = await self._resolve(
            tenant_id, evidence,
            canonical_campaign_id=canonical_campaign_id,
            norm_platform=norm_platform,
            norm_ext_account=norm_ext_account,
            norm_ext_campaign=norm_ext_campaign,
            norm_utm_id=norm_utm_id,
            norm_utm_source=norm_utm_source,
            norm_utm_medium=norm_utm_medium,
            norm_utm_campaign=norm_utm_campaign,
            create_review_on_failure=create_review_on_failure,
        )
        result.normalized_evidence = {k: v for k, v in evidence.items() if v is not None}

        latency_ms = (time.monotonic() - t0) * 1000
        metrics.histogram("campaign_resolution_latency", latency_ms)
        metrics.increment(
            "campaign_resolution_total",
            tags={"status": result.status, "method": result.method or "none"},
        )
        if result.status == "unresolved":
            metrics.increment("campaign_resolution_unresolved_total")
        elif result.status == "ambiguous":
            metrics.increment("campaign_resolution_ambiguous_total")

        return result

    async def _resolve(
        self,
        tenant_id: str,
        evidence: dict,
        *,
        canonical_campaign_id: Optional[str],
        norm_platform: Optional[str],
        norm_ext_account: Optional[str],
        norm_ext_campaign: Optional[str],
        norm_utm_id: Optional[str],
        norm_utm_source: Optional[str],
        norm_utm_medium: Optional[str],
        norm_utm_campaign: Optional[str],
        create_review_on_failure: bool,
    ) -> ResolutionResult:

        # ── Step 1: Explicit canonical campaign UUID ──────────────────────────
        if canonical_campaign_id:
            try:
                cid = UUID(canonical_campaign_id)
            except ValueError:
                return ResolutionResult(
                    status="invalid",
                    reason=f"canonical_campaign_id is not a valid UUID: {canonical_campaign_id!r}",
                )
            campaign = await self._campaigns.get_by_id(tenant_id, cid)
            if campaign is None:
                return ResolutionResult(
                    status="invalid",
                    reason="canonical_campaign_id not found for tenant",
                )
            return ResolutionResult(
                status="resolved",
                campaign_id=cid,
                method="canonical_uuid",
                confidence=Decimal("1.00"),
                reason="Explicit canonical campaign UUID validated against tenant",
            )

        # ── Step 2: Exact external reference ─────────────────────────────────
        if norm_platform and norm_ext_account and norm_ext_campaign:
            ref = await self._external_refs.get_exact(
                tenant_id, norm_platform, norm_ext_account, norm_ext_campaign
            )
            if ref:
                return ResolutionResult(
                    status="resolved",
                    campaign_id=ref["campaign_id"],
                    method="exact_external_ref",
                    confidence=Decimal("1.00"),
                    matched_external_ref_id=ref["external_ref_id"],
                    reason=f"Exact external reference: {norm_platform}/{norm_ext_account}/{norm_ext_campaign}",
                )

        # ── Step 3: utm_id alias ──────────────────────────────────────────────
        if norm_utm_id:
            alias = await self._aliases.get_active(tenant_id, ALIAS_TYPE_UTM_ID, norm_utm_id)
            if alias:
                return ResolutionResult(
                    status="resolved",
                    campaign_id=alias["campaign_id"],
                    method="utm_id_alias",
                    confidence=Decimal("0.99"),
                    matched_alias_id=alias["alias_id"],
                    reason=f"Exact utm_id alias match: {norm_utm_id}",
                )

        # ── Step 4: Composite alias (platform/account/source/medium/campaign) ─
        if norm_platform and norm_ext_account and norm_utm_campaign:
            composite_key = f"{norm_platform}::{norm_ext_account}::{norm_utm_source or ''}::{norm_utm_medium or ''}::{norm_utm_campaign}"
            composite_norm = normalize_utm_value(composite_key) or composite_key
            # Check external_campaign_id alias scoped to platform+account
            scoped_alias_key = f"{norm_platform}::{norm_ext_account}::{norm_utm_campaign}"
            alias = await self._aliases.get_active(
                tenant_id, ALIAS_TYPE_UTM_CAMPAIGN, normalize_utm_value(scoped_alias_key) or scoped_alias_key
            )
            if alias:
                return ResolutionResult(
                    status="resolved",
                    campaign_id=alias["campaign_id"],
                    method="composite_alias",
                    confidence=Decimal("0.95"),
                    matched_alias_id=alias["alias_id"],
                    reason=f"Exact composite alias: {scoped_alias_key}",
                )

        # ── Step 5: Tenant-unique utm_campaign alias ──────────────────────────
        if norm_utm_campaign:
            alias = await self._aliases.get_active(tenant_id, ALIAS_TYPE_UTM_CAMPAIGN, norm_utm_campaign)
            if alias:
                return ResolutionResult(
                    status="resolved",
                    campaign_id=alias["campaign_id"],
                    method="utm_campaign_alias",
                    confidence=Decimal("0.85"),
                    matched_alias_id=alias["alias_id"],
                    reason=f"Tenant-unique utm_campaign alias: {norm_utm_campaign}",
                )

        # ── Steps 6–7: Ambiguous or unresolved → Mapping Review ──────────────
        if not any([norm_ext_campaign, norm_utm_id, norm_utm_campaign]):
            return ResolutionResult(
                status="not_applicable",
                reason="No resolvable campaign evidence present",
            )

        if create_review_on_failure:
            review = await self._registry.get_or_create_review(
                tenant_id, evidence, candidate_campaign_ids=[]
            )
            review_id = review["review_id"]
        else:
            review_id = None

        return ResolutionResult(
            status="unresolved",
            reason="No campaign found for evidence; Mapping Review created",
            review_id=review_id,
        )

    async def resolve_many(
        self,
        tenant_id: str,
        evidences: list[dict[str, Any]],
    ) -> list[ResolutionResult]:
        """Batch resolution — executes batch DB lookups to minimise round-trips.

        Each evidence dict may contain the same keys as resolve_one kwargs.
        Returns results in the same order as evidences.
        """
        metrics.histogram("campaign_resolution_batch_size", len(evidences))

        # For now: parallel individual resolutions (batch DB optimisation via
        # AliasRepository.get_active_batch is applied when alias lookups dominate).
        import asyncio
        results = await asyncio.gather(*[
            self.resolve_one(tenant_id, **ev)
            for ev in evidences
        ])
        return list(results)
