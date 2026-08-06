"""Gold materialization workers — aggregate Silver/canonical facts to ClickHouse Gold tables."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from shared.cis.clickhouse import ClickHouseClient
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.spend_repo import SpendRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = logging.getLogger("aether.measurement.gold_materializer")

_ch_client: Optional[ClickHouseClient] = None


async def _ch() -> ClickHouseClient:
    global _ch_client
    if _ch_client is None:
        _ch_client = ClickHouseClient()
        await _ch_client.connect()
    return _ch_client


@dataclass
class BackfillResult:
    tenant_id: str
    start_date: date
    end_date: date
    campaign_perf_rows: int
    journey_econ_rows: int
    attribution_credit_rows: int
    errors: list[str]


async def materialize_campaign_performance_daily(
    tenant_id: str,
    target_date: date,
    *,
    restatement_reason: Optional[str] = None,
) -> int:
    """Aggregate attribution credits + spend_records for a campaign/date into gold_ad_spend.

    Uses ReplacingMergeTree semantics — rows with a newer ingested_at replace older ones.
    Returns the number of rows written.
    """
    spend_repo = SpendRepository()
    run_repo = AttributionRunRepository()
    ch = await _ch()

    period_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)

    spend_rows = await spend_repo.list_by_tenant(
        tenant_id,
        period_start=period_start,
        period_end=period_end,
        limit=10000,
    )

    by_campaign: dict[str, dict[str, Any]] = {}
    for sr in spend_rows:
        cid = sr.get("campaign_id") or "__no_campaign__"
        platform = sr.get("platform") or "unknown"
        key = f"{cid}:{platform}"
        if key not in by_campaign:
            by_campaign[key] = {
                "tenant_id": tenant_id,
                "campaign_id": cid,
                "platform": platform,
                "date": target_date.isoformat(),
                "spend_usd": Decimal("0"),
                "impressions": 0,
                "clicks": 0,
                "revenue_attributed_usd": Decimal("0"),
                "conversions": 0,
                # Fractional attributed-conversion credit, preserved for the
                # integrity feed (the ClickHouse column stays integer).
                "conversions_fractional": Decimal("0"),
            }
        rec = by_campaign[key]
        rec["spend_usd"] += _to_decimal(sr.get("total_cost")) or Decimal("0")
        rec["impressions"] += int(sr.get("impressions", 0))
        rec["clicks"] += int(sr.get("clicks", 0))

    # Pull active attribution credits for campaign + date
    for key, rec in by_campaign.items():
        campaign_id = rec["campaign_id"]
        if campaign_id == "__no_campaign__":
            continue
        summary = await run_repo.campaign_credit_summary(
            tenant_id,
            campaign_id,
            start_date=period_start,
            end_date=period_end,
        )
        rec["revenue_attributed_usd"] = summary.get("total_attributed_net_revenue") or Decimal("0")
        # Preserve the FRACTIONAL attributed conversions. The gold ClickHouse
        # column keeps an integer for schema compatibility, but the measurement
        # plane (the integrity source of truth) must not truncate credit — a
        # int() here previously understated CPA and conversion_rate.
        rec["conversions_fractional"] = (
            _to_decimal(summary.get("total_attributed_conversions")) or Decimal("0")
        )
        rec["conversions"] = int(rec["conversions_fractional"])

    now = datetime.now(timezone.utc)
    gold_rows = []
    for rec in by_campaign.values():
        spend = float(rec["spend_usd"])
        revenue = float(rec["revenue_attributed_usd"])
        impressions = rec["impressions"]
        clicks = rec["clicks"]
        conversions = rec["conversions"]

        gold_rows.append({
            "tenant_id": tenant_id,
            "campaign_id": rec["campaign_id"],
            "platform": rec["platform"],
            "utm_campaign": None,
            "date": rec["date"],
            "spend_usd": spend,
            "impressions": impressions,
            "clicks": clicks,
            "cpm": (spend / impressions * 1000) if impressions > 0 else 0.0,
            "cpc": (spend / clicks) if clicks > 0 else 0.0,
            "ctr": (clicks / impressions) if impressions > 0 else 0.0,
            "conversions": conversions,
            "revenue_attributed_usd": revenue,
            "ingested_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        })

    if gold_rows:
        await ch.insert("gold_ad_spend", gold_rows)
        logger.info(
            "Materialized gold_ad_spend: tenant=%s date=%s rows=%d",
            tenant_id, target_date, len(gold_rows),
        )
        # Feed the Measurement Integrity Plane with the tenant-day conversion
        # rate: an honest value_state (never a bare 0 when there are no clicks —
        # insufficient_data below the sample floor) plus a Wilson interval. The
        # gold ClickHouse row keeps its float for compatibility; the plane
        # (/v1/measurement) is the integrity source of truth. Best-effort — the
        # gold materialization must never fail on this telemetry.
        try:
            from repositories.measurement_results_repo import (
                get_measurement_results_repository,
            )
            from shared.measurement.compute import record_rate
            from shared.measurement.context import MeasurementContext
            from shared.measurement.registry import REGISTRY_VERSION

            total_clicks = sum(int(r["clicks"]) for r in gold_rows)
            # Feed the plane the FRACTIONAL attributed conversions, not the
            # integer gold-column projection, so conversion_rate is not
            # understated by per-campaign truncation.
            total_conversions = float(
                sum(
                    (_to_decimal(r["conversions_fractional"]) or Decimal("0"))
                    for r in by_campaign.values()
                )
            )
            ctx = MeasurementContext(
                tenant_id=tenant_id,
                window_start=period_start.isoformat(),
                window_end=period_end.isoformat(),
                registry_version=REGISTRY_VERSION,
            )
            await record_rate(
                get_measurement_results_repository(),
                ctx,
                metric_name="conversion_rate",
                numerator=total_conversions,
                denominator=total_clicks,
                lineage={
                    "source": "gold_ad_spend",
                    "date": target_date.isoformat(),
                    "campaigns": len(gold_rows),
                },
                restatement_reason=restatement_reason,
            )
        except Exception as exc:  # pragma: no cover — telemetry must not break materialization
            logger.debug("measurement plane conversion_rate record skipped: %s", exc)

    return len(gold_rows)


async def materialize_journey_economics(
    tenant_id: str,
    journey_id: str,
) -> int:
    """Materialize journey-level economics into gold_journey_economics.

    Computes ROAS, CPA, attributed revenue for a journey version.
    Returns the number of rows written.
    """
    journey_repo = JourneyRepository()
    run_repo = AttributionRunRepository()
    spend_repo = SpendRepository()
    ch = await _ch()

    journey = await journey_repo.get_current(tenant_id, journey_id)
    if journey is None:
        logger.warning("Journey not found for materialization: %s", journey_id)
        return 0

    profile_id = journey.get("profile_id") or journey.get("cluster_id") or ""
    campaign_ids = journey.get("campaign_ids") or []
    if isinstance(campaign_ids, str):
        import json
        campaign_ids = json.loads(campaign_ids)

    conversion_ids = journey.get("conversion_ids") or []
    if isinstance(conversion_ids, str):
        import json
        conversion_ids = json.loads(conversion_ids)

    total_attributed_revenue = Decimal("0")
    total_spend = Decimal("0")
    conversion_count = 0

    for conv_id in conversion_ids:
        credits = await run_repo.list_credits_for_conversion(tenant_id, conv_id, active_only=True)
        for credit in credits:
            total_attributed_revenue += _to_decimal(credit.get("attributed_net_revenue") or "0") or Decimal("0")
        if credits:
            conversion_count += 1

    started_at = _parse_ts(journey.get("started_at"))
    ended_at = _parse_ts(journey.get("ended_at")) or datetime.now(timezone.utc)

    for cid in campaign_ids:
        total_spend += await spend_repo.total_spend(
            tenant_id, cid,
            period_start=started_at,
            period_end=ended_at,
        )

    roas = float(total_attributed_revenue / total_spend) if total_spend > Decimal("0") else 0.0
    cpa = float(total_spend / conversion_count) if conversion_count > 0 else 0.0

    now = datetime.now(timezone.utc)
    gold_row = {
        "entity_id": profile_id,
        "tenant_id": tenant_id,
        "journey_id": journey_id,
        "window_days": None,
        "campaign_id": campaign_ids[0] if campaign_ids else None,
        "channel": None,
        "platform": None,
        "revenue_attributed_usd": float(total_attributed_revenue),
        "ad_spend_usd": float(total_spend),
        "roas": roas,
        "cpa_usd": cpa,
        "ltv_predicted_usd": 0.0,
        "ltv_actual_usd": float(total_attributed_revenue),
        "aov_usd": float(total_attributed_revenue / conversion_count) if conversion_count > 0 else 0.0,
        "repeat_count": conversion_count,
        "retarget_score": 0.0,
        "retarget_recommendation_id": None,
        "time_impression_to_click_ms": None,
        "time_click_to_visit_ms": None,
        "time_visit_to_connect_ms": None,
        "time_connect_to_swap_ms": None,
        "time_swap_to_liquidity_ms": None,
        "computed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    await ch.insert("gold_journey_economics", [gold_row])
    logger.info("Materialized gold_journey_economics: tenant=%s journey=%s", tenant_id, journey_id)
    return 1


async def materialize_attribution_credits(
    tenant_id: str,
    conversion_id: str,
    *,
    restatement_reason: Optional[str] = None,
) -> int:
    """Re-materialize campaign performance after a new attribution run completes."""
    run_repo = AttributionRunRepository()
    active_run = await run_repo.get_active_run(tenant_id, conversion_id)
    if active_run is None:
        return 0

    credits = await run_repo.list_credits_for_conversion(tenant_id, conversion_id, active_only=True)
    campaign_ids = {c.get("campaign_id") for c in credits if c.get("campaign_id")}

    rows_written = 0
    today = date.today()
    for _ in campaign_ids:
        rows_written += await materialize_campaign_performance_daily(
            tenant_id, today, restatement_reason=restatement_reason
        )

    return rows_written


async def backfill_tenant(
    tenant_id: str,
    start_date: date,
    end_date: date,
    *,
    restatement_reason: Optional[str] = None,
) -> BackfillResult:
    """Backfill all Gold tables for a tenant across a date range."""
    journey_repo = JourneyRepository()
    errors: list[str] = []
    campaign_perf_rows = 0
    journey_econ_rows = 0
    attribution_credit_rows = 0

    current = start_date
    while current <= end_date:
        try:
            n = await materialize_campaign_performance_daily(
                tenant_id, current, restatement_reason=restatement_reason
            )
            campaign_perf_rows += n
        except Exception as exc:
            errors.append(f"campaign_perf {current}: {exc}")
        current += timedelta(days=1)

    try:
        journeys = await journey_repo.list_current(tenant_id, limit=10000)
        for journey in journeys:
            jid = journey.get("journey_id")
            try:
                n = await materialize_journey_economics(tenant_id, jid)
                journey_econ_rows += n
            except Exception as exc:
                errors.append(f"journey_econ {jid}: {exc}")
    except Exception as exc:
        errors.append(f"journey_list: {exc}")

    logger.info(
        "Backfill complete: tenant=%s %s-%s campaign_perf=%d journey_econ=%d errors=%d",
        tenant_id, start_date, end_date, campaign_perf_rows, journey_econ_rows, len(errors),
    )

    return BackfillResult(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        campaign_perf_rows=campaign_perf_rows,
        journey_econ_rows=journey_econ_rows,
        attribution_credit_rows=attribution_credit_rows,
        errors=errors,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
