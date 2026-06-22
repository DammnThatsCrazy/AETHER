"""Per-conversion attribution engine — orchestrates runs, persists credits, manages active run lifecycle."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from services.attribution.models import Touchpoint
from services.attribution.resolver import AttributionConfig, AttributionResolver
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = logging.getLogger("aether.measurement.attribution_engine")

_CREDIT_RECONCILIATION_TOLERANCE = Decimal("0.001")

_CODE_VERSION = "1.0"

_resolver = AttributionResolver(
    AttributionConfig(default_model="last_touch", lookback_window_hours=720)
)


class AttributionEngine:
    """Canonical per-conversion attribution runner.

    One AttributionRun is created per invocation. On success the run is
    persisted with status='complete' and is_active=TRUE. The previous active
    run for the same conversion is marked is_active=FALSE atomically.

    Uses the 8 built-in attribution models from services.attribution.models.
    Does not duplicate model logic.
    """

    def __init__(self) -> None:
        self._run_repo = AttributionRunRepository()
        self._conversion_repo = ConversionRepository()
        self._journey_repo = JourneyRepository()
        self._touchpoint_repo = TouchpointRepository()

    async def run_for_conversion(
        self,
        tenant_id: str,
        conversion_id: str,
        *,
        model_type: Optional[str] = None,
        model_config_id: Optional[str] = None,
        lookback_hours: int = 720,
        view_lookback_hours: int = 168,
        identity_confidence_min: float = 0.0,
        fraud_policy: str = "exclude",
        trigger_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run attribution for one conversion and persist the result.

        Returns the completed attribution run dict.
        Raises ValueError if the conversion is not found or not eligible.
        """
        # 1. Load conversion
        conversion = await self._conversion_repo.get(tenant_id, conversion_id)
        if conversion is None:
            raise ValueError(f"Conversion {conversion_id} not found for tenant {tenant_id}")
        if not conversion.get("attribution_eligible", True):
            raise ValueError(f"Conversion {conversion_id} is not attribution-eligible")

        effective_model = model_type or "last_touch"

        # 2. Create pending run
        run = await self._run_repo.create_run({
            "tenant_id": tenant_id,
            "conversion_id": conversion_id,
            "model_type": effective_model,
            "model_version": "1.0",
            "code_version": _CODE_VERSION,
            "model_config_id": model_config_id,
            "status": "pending",
            "currency": conversion.get("currency", "USD"),
            "eligible_revenue": conversion.get("net_value") or conversion.get("gross_value"),
        })
        run_id = run["attribution_run_id"]

        try:
            await self._run_repo.update_run(run_id, {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            })

            # 3. Load active journey version for the profile
            profile_id = conversion.get("profile_id") or conversion.get("cluster_id")
            journey_versions = []
            touchpoint_ids: list[str] = []
            journey_id: Optional[str] = None
            journey_version_id: Optional[str] = None

            if profile_id:
                journey_versions = await self._journey_repo.find_current_for_profile(tenant_id, profile_id)
                if journey_versions:
                    jv = journey_versions[0]
                    journey_id = jv.get("journey_id")
                    journey_version_id = jv.get("journey_version_id")
                    touchpoint_ids = jv.get("touchpoint_ids") or []
                    if isinstance(touchpoint_ids, str):
                        import json
                        touchpoint_ids = json.loads(touchpoint_ids)

            # 4. Load touchpoints from journey or fall back to campaign touchpoints
            raw_touchpoints: list[dict[str, Any]] = []
            excluded_ids: list[str] = []
            exclusion_reasons: dict[str, str] = {}

            occurred_at_str = conversion.get("occurred_at", "")
            conversion_ts = _parse_ts(occurred_at_str) or datetime.now(timezone.utc)
            click_cutoff = conversion_ts - timedelta(hours=lookback_hours)
            view_cutoff = conversion_ts - timedelta(hours=view_lookback_hours)

            if touchpoint_ids:
                for tp_id in touchpoint_ids:
                    tp = await self._touchpoint_repo.get(tenant_id, tp_id)
                    if tp is None:
                        continue
                    tp_ts = _parse_ts(tp.get("occurred_at"))
                    if tp_ts is None:
                        excluded_ids.append(tp_id)
                        exclusion_reasons[tp_id] = "missing_timestamp"
                        continue

                    is_view = tp.get("is_view_through", False)
                    cutoff = view_cutoff if is_view else click_cutoff
                    if tp_ts < cutoff:
                        excluded_ids.append(tp_id)
                        exclusion_reasons[tp_id] = "outside_lookback"
                        continue

                    if identity_confidence_min > 0.0:
                        conf = tp.get("identity_confidence")
                        if conf is not None and float(conf) < identity_confidence_min:
                            excluded_ids.append(tp_id)
                            exclusion_reasons[tp_id] = "low_identity_confidence"
                            continue

                    raw_touchpoints.append(tp)
            else:
                # No journey — try to find touchpoints by profile/anonymous_id
                if profile_id:
                    raw_touchpoints = await self._touchpoint_repo.list_by_profile(
                        tenant_id, profile_id,
                        before_occurred=conversion_ts,
                        limit=500,
                    )

            # 5. Build Touchpoint objects for resolver
            resolver_touchpoints = _build_resolver_touchpoints(raw_touchpoints)

            input_count = len(raw_touchpoints)
            excluded_count = len(excluded_ids)

            # 6. Run attribution model
            result = await _resolver.resolve(
                user_id=profile_id or conversion_id,
                event={"event_type": "conversion", "conversion_id": conversion_id},
                touchpoints=[_touchpoint_to_resolver_dict(tp) for tp in raw_touchpoints],
                model_name=effective_model,
            )

            # 7. Build credit rows
            eligible_revenue = _to_decimal(
                conversion.get("net_value") or conversion.get("gross_value") or "0"
            ) or Decimal("0")

            credit_rows: list[dict[str, Any]] = []
            total_weight = Decimal("0")

            for credit in result.credits:
                weight = Decimal(str(round(credit.weight, 8)))
                total_weight += weight

                # Find the matching raw touchpoint to get campaign/channel metadata
                tp_meta = _find_touchpoint_by_channel(
                    raw_touchpoints,
                    credit.touchpoint.channel,
                    credit.touchpoint.source,
                )
                tp_id = tp_meta.get("touchpoint_id") if tp_meta else None

                credit_rows.append({
                    "credit_id": str(uuid4()),
                    "tenant_id": tenant_id,
                    "attribution_run_id": run_id,
                    "conversion_id": conversion_id,
                    "touchpoint_id": tp_id,
                    "campaign_id": tp_meta.get("campaign_id") if tp_meta else None,
                    "ad_group_id": tp_meta.get("ad_group_id") if tp_meta else None,
                    "ad_set_id": tp_meta.get("ad_set_id") if tp_meta else None,
                    "creative_id": tp_meta.get("creative_id") if tp_meta else None,
                    "ad_id": tp_meta.get("ad_id") if tp_meta else None,
                    "placement_id": tp_meta.get("placement_id") if tp_meta else None,
                    "keyword_id": tp_meta.get("keyword_id") if tp_meta else None,
                    "channel": credit.touchpoint.channel,
                    "source": credit.touchpoint.source,
                    "credit_weight": str(weight),
                    "attributed_conversion_count": str(weight),
                    "attributed_gross_revenue": str(weight * eligible_revenue),
                    "attributed_net_revenue": str(weight * eligible_revenue),
                    "explanation": f"{effective_model}: weight={float(weight):.4f}",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

            unattributed = Decimal("1") - total_weight
            if unattributed < Decimal("0"):
                unattributed = Decimal("0")

            # 8. Validate credit reconciliation
            if abs(total_weight + unattributed - Decimal("1")) > _CREDIT_RECONCILIATION_TOLERANCE:
                logger.error(
                    "Credit reconciliation failed: run_id=%s total_weight=%s unattributed=%s",
                    run_id, total_weight, unattributed,
                )

            # 9. Deactivate prior active runs
            await self._run_repo.deactivate_prior_runs(tenant_id, conversion_id)

            # 10. Persist credits
            await self._run_repo.insert_credits(credit_rows)

            # 11. Mark run complete and active
            completed_run = await self._run_repo.update_run(run_id, {
                "status": "complete",
                "is_active": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "credit_total": str(total_weight),
                "unattributed_credit": str(unattributed),
                "input_touchpoint_count": input_count,
                "excluded_touchpoint_count": excluded_count,
            })

            if journey_id:
                await self._run_repo.update_run(run_id, {
                    "journey_id": journey_id,
                    "journey_version_id": journey_version_id,
                })

            logger.info(
                "Attribution complete: run_id=%s conversion=%s model=%s credits=%d weight_sum=%s",
                run_id, conversion_id, effective_model, len(credit_rows), total_weight,
            )
            return completed_run or run

        except Exception as exc:
            await self._run_repo.update_run(run_id, {
                "status": "failed",
                "failure_reason": str(exc)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.exception("Attribution failed: run_id=%s conversion=%s", run_id, conversion_id)
            raise

    async def run_backfill(
        self,
        tenant_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        model_type: str = "last_touch",
    ) -> dict[str, Any]:
        """Run attribution for all unattributed conversions in a time window.

        Returns a summary dict with counts of success/failure.
        """
        from services.measurement.repositories.conversion_repo import ConversionRepository
        conv_repo = ConversionRepository()

        total = 0
        success = 0
        failed = 0

        # Iterate with cursor pagination to avoid loading all at once
        cursor = None
        while True:
            batch = await conv_repo.list_by_tenant(
                tenant_id,
                after_occurred=start_at,
                before_occurred=end_at,
                attribution_eligible_only=True,
                limit=50,
                cursor=cursor,
            )
            if not batch:
                break

            for conv in batch:
                total += 1
                conv_id = conv.get("conversion_id")
                # Skip if already has active run
                existing = await self._run_repo.get_active_run(tenant_id, conv_id)
                if existing and existing.get("status") == "complete":
                    continue
                try:
                    await self.run_for_conversion(
                        tenant_id, conv_id,
                        model_type=model_type,
                        trigger_reason="backfill",
                    )
                    success += 1
                except Exception as exc:
                    failed += 1
                    logger.warning("Backfill skip: conversion=%s error=%s", conv_id, exc)

            if len(batch) < 50:
                break
            cursor = batch[-1].get("occurred_at")

        return {
            "tenant_id": tenant_id,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "model_type": model_type,
            "total_conversions": total,
            "success": success,
            "failed": failed,
        }

    async def compare_models(
        self,
        tenant_id: str,
        model_a: str,
        model_b: str,
        conversion_ids: list[str],
    ) -> dict[str, Any]:
        """Run two models on the same conversions and return a credit diff.

        This runs both models WITHOUT persisting either as active — for comparison only.
        Neither run is marked is_active=TRUE.
        """
        results: list[dict[str, Any]] = []
        for conv_id in conversion_ids:
            conversion = await self._conversion_repo.get(tenant_id, conv_id)
            if conversion is None:
                continue
            profile_id = conversion.get("profile_id") or conversion.get("cluster_id")
            raw_touchpoints: list[dict[str, Any]] = []
            if profile_id:
                raw_touchpoints = await self._touchpoint_repo.list_by_profile(
                    tenant_id, profile_id, limit=500,
                )

            result_a = await _resolver.resolve(
                user_id=profile_id or conv_id,
                event={"event_type": "conversion"},
                touchpoints=[_touchpoint_to_resolver_dict(tp) for tp in raw_touchpoints],
                model_name=model_a,
            )
            result_b = await _resolver.resolve(
                user_id=profile_id or conv_id,
                event={"event_type": "conversion"},
                touchpoints=[_touchpoint_to_resolver_dict(tp) for tp in raw_touchpoints],
                model_name=model_b,
            )

            results.append({
                "conversion_id": conv_id,
                "model_a": model_a,
                "model_b": model_b,
                "credits_a": [c.to_dict() for c in result_a.credits],
                "credits_b": [c.to_dict() for c in result_b.credits],
            })

        return {
            "tenant_id": tenant_id,
            "model_a": model_a,
            "model_b": model_b,
            "conversion_count": len(results),
            "comparisons": results,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _touchpoint_to_resolver_dict(tp: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical touchpoint row to the dict format expected by AttributionResolver."""
    return {
        "channel": tp.get("channel", "unknown"),
        "source": tp.get("source", "unknown"),
        "campaign": tp.get("campaign_id", ""),
        "timestamp": tp.get("occurred_at", datetime.now(timezone.utc).isoformat()),
        "event_type": tp.get("touchpoint_type", "page_view"),
        "properties": {
            "touchpoint_id": tp.get("touchpoint_id"),
            "is_view_through": tp.get("is_view_through", False),
            "is_click_through": tp.get("is_click_through", False),
            "dwell_ms": tp.get("dwell_ms"),
        },
    }


def _build_resolver_touchpoints(raw: list[dict[str, Any]]) -> list[Touchpoint]:
    result = []
    for tp in raw:
        ts = _parse_ts(tp.get("occurred_at")) or datetime.now(timezone.utc)
        result.append(Touchpoint(
            channel=tp.get("channel", "unknown"),
            source=tp.get("source", "unknown"),
            campaign=tp.get("campaign_id", ""),
            timestamp=ts,
            event_type=tp.get("touchpoint_type", "page_view"),
            properties={"touchpoint_id": tp.get("touchpoint_id")},
        ))
    return result


def _find_touchpoint_by_channel(
    touchpoints: list[dict[str, Any]],
    channel: str,
    source: str,
) -> Optional[dict[str, Any]]:
    """Find the last touchpoint matching channel+source for credit metadata."""
    matches = [
        tp for tp in reversed(touchpoints)
        if tp.get("channel") == channel and tp.get("source") == source
    ]
    return matches[0] if matches else None


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
