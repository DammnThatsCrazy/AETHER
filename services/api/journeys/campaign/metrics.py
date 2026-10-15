"""Campaign Intelligence observability — registry, resolver, sources, backfill."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

from shared.logger.logger import metrics as _metrics


class CampaignRegistryMetrics:
    """Metrics for CampaignRegistryService — upserts, aliases, reviews."""

    def record_upsert(self, tenant_id: str, origin: str) -> None:
        _metrics.increment(
            "campaign_registry_upsert_total",
            labels={"tenant_id": tenant_id, "origin": origin},
        )

    def record_upsert_conflict(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_registry_conflict_total",
            labels={"tenant_id": tenant_id},
        )

    def record_external_ref_upsert(self, platform: str) -> None:
        _metrics.increment(
            "campaign_external_ref_upsert_total",
            labels={"platform": platform},
        )

    def record_alias_created(self, alias_type: str) -> None:
        _metrics.increment(
            "campaign_alias_created_total",
            labels={"alias_type": alias_type},
        )

    def record_alias_conflict(self, alias_type: str) -> None:
        _metrics.increment(
            "campaign_alias_conflict_total",
            labels={"alias_type": alias_type},
        )

    def record_review_created(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_mapping_review_created_total",
            labels={"tenant_id": tenant_id},
        )

    def record_review_resolved(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_mapping_review_resolved_total",
            labels={"tenant_id": tenant_id},
        )

    def record_review_ignored(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_mapping_review_ignored_total",
            labels={"tenant_id": tenant_id},
        )

    def set_open_reviews(self, tenant_id: str, count: int) -> None:
        _metrics.gauge(
            "campaign_mapping_review_open",
            count,
            labels={"tenant_id": tenant_id},
        )


class CampaignResolverMetrics:
    """Metrics for CampaignResolver — resolution outcomes, latency, cache."""

    @contextmanager
    def timed_resolve(self, tenant_id: str) -> Generator[None, None, None]:
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            _metrics.histogram(
                "campaign_resolution_latency_seconds",
                elapsed,
                labels={"tenant_id": tenant_id},
            )

    def record_resolution(self, status: str, method: str | None) -> None:
        _metrics.increment(
            "campaign_resolution_total",
            labels={"status": status, "method": method or "none"},
        )

    def record_batch_size(self, size: int) -> None:
        _metrics.histogram("campaign_resolution_batch_size", size)

    def record_cache_hit(self) -> None:
        _metrics.increment("campaign_resolution_cache_hit_total")

    def record_cache_miss(self) -> None:
        _metrics.increment("campaign_resolution_cache_miss_total")

    def set_spend_mapping_rate(self, tenant_id: str, rate: float) -> None:
        _metrics.gauge(
            "campaign_spend_mapping_rate",
            rate,
            labels={"tenant_id": tenant_id},
        )

    def set_touchpoint_mapping_rate(self, tenant_id: str, rate: float) -> None:
        _metrics.gauge(
            "campaign_touchpoint_mapping_rate",
            rate,
            labels={"tenant_id": tenant_id},
        )


class CampaignSourceMetrics:
    """Metrics for campaign source syncs."""

    def record_sync(self, platform: str, status: str) -> None:
        _metrics.increment(
            "campaign_source_sync_total",
            labels={"platform": platform, "status": status},
        )

    def set_source_freshness_seconds(self, platform: str, tenant_id: str, age_seconds: float) -> None:
        _metrics.gauge(
            "campaign_source_freshness_seconds",
            age_seconds,
            labels={"platform": platform, "tenant_id": tenant_id},
        )


class CampaignBackfillMetrics:
    """Metrics for the historical campaign ID backfill script."""

    def record_reprocess_requested(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_reprocess_requested_total",
            labels={"tenant_id": tenant_id},
        )

    def record_reprocess_completed(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_reprocess_completed_total",
            labels={"tenant_id": tenant_id},
        )

    def record_reprocess_failed(self, tenant_id: str) -> None:
        _metrics.increment(
            "campaign_reprocess_failed_total",
            labels={"tenant_id": tenant_id},
        )

    def set_backfill_progress(self, tenant_id: str, pct: float) -> None:
        _metrics.gauge(
            "campaign_backfill_progress",
            pct,
            labels={"tenant_id": tenant_id},
        )


# Module-level singletons
campaign_registry_metrics = CampaignRegistryMetrics()
campaign_resolver_metrics = CampaignResolverMetrics()
campaign_source_metrics = CampaignSourceMetrics()
campaign_backfill_metrics = CampaignBackfillMetrics()
