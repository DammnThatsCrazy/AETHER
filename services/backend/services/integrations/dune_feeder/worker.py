"""Dune polling worker — periodic Bronze ingest + Bronze→Silver promotion.

Runs as an asyncio background task. Interval is configurable via
DUNE_POLL_INTERVAL_SECONDS (default 3600).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from shared.logger.logger import get_logger, metrics
from services.integrations.dune_feeder.service import (
    PromotionService,
    _feeder_configs,
    record_feeder_run,
)
from repositories.lake import BronzeRepository, SilverRepository

logger = get_logger("aether.feeder.dune.worker")

_INTERVAL = int(os.getenv("DUNE_POLL_INTERVAL_SECONDS", "3600"))

_bronze = BronzeRepository("dune_feeder")
_silver = SilverRepository("dune_feeder")
_promotion_service = PromotionService()


async def run_dune_poll_cycle() -> dict[str, Any]:
    """Fetch all active Dune feeder configs, pull rows, ingest to Bronze,
    promote to Silver.  Returns a summary dict."""
    configs = await _feeder_configs.list_all(limit=1000)
    total_tenants = 0
    total_ingested = 0
    total_promoted = 0
    total_errors = 0

    for cfg in configs:
        if not cfg.get("enabled", True):
            continue
        tenant_id: str = cfg.get("tenant_id", "")
        if not tenant_id:
            continue

        try:
            from services.integrations.connectors.adapters import DuneConnector
            from services.integrations.connectors.base import ConnectorConfig

            connector_cfg = ConnectorConfig(
                tenant_id=tenant_id,
                connector_type="dune",
                config=cfg.get("connector_config", {}),
                vault_secret_key=cfg.get("vault_secret_key", ""),
            )
            connector = DuneConnector(connector_cfg)
            rows = await connector.pull()

            ingested = 0
            for i, row in enumerate(rows):
                provider_id = f"{cfg.get('query_id', 'unknown')}:worker:{i}"
                _, is_new = await _bronze.ingest(
                    source="dune",
                    source_tag=f"dune:{cfg.get('query_id', 'unknown')}",
                    provider_record_id=provider_id,
                    payload={**row, "tenant_id": tenant_id},
                    schema_version="1.0",
                    entity_id=row.get("entity_id", provider_id),
                    entity_type=row.get("entity_type", "dune_row"),
                    tenant_id=tenant_id,
                )
                if is_new:
                    ingested += 1

            source_tag = f"dune:{cfg.get('query_id', 'unknown')}"
            promotion_result = await _promotion_service.promote_batch(
                _bronze, _silver,
                source_tag=source_tag,
                tenant_id=tenant_id,
                required_fields=cfg.get("required_fields", []),
                max_age_hours=cfg.get("max_age_hours", 24),
                null_rate_threshold=cfg.get("null_rate_threshold", 0.3),
            )

            await record_feeder_run(
                tenant_id=tenant_id,
                source_tag=source_tag,
                rows_ingested=ingested,
                rows_promoted=promotion_result.get("promoted_count", 0),
                rows_rejected=promotion_result.get("rejected_count", 0),
            )

            total_tenants += 1
            total_ingested += ingested
            total_promoted += promotion_result.get("promoted_count", 0)
            metrics.increment("dune_poll_tenant_cycle", labels={"tenant_id": tenant_id})

        except Exception as e:
            total_errors += 1
            logger.error(f"Dune poll cycle failed for tenant {tenant_id}: {e}")
            metrics.increment("dune_poll_tenant_error", labels={"tenant_id": tenant_id})

    summary = {
        "tenants": total_tenants,
        "ingested": total_ingested,
        "promoted": total_promoted,
        "errors": total_errors,
    }
    logger.info(f"Dune poll cycle complete: {summary}")
    metrics.increment("dune_poll_cycle_complete")
    return summary


async def dune_poll_loop(interval_seconds: int = _INTERVAL) -> None:
    """Background task: poll Dune on a schedule for all tenants."""
    logger.info(f"Dune poll worker started: interval={interval_seconds}s")
    while True:
        try:
            await run_dune_poll_cycle()
        except Exception as e:
            logger.error(f"Dune poll loop error: {e}")
            metrics.increment("dune_poll_loop_error")
        await asyncio.sleep(interval_seconds)
