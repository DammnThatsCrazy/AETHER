"""Per-conversion attribution engine — orchestrates runs, persists credits, manages active run lifecycle."""

from __future__ import annotations

import logging
import os
import json
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
        lookback_hours: Optional[int] = None,
        view_lookback_hours: Optional[int] = None,
        identity_confidence_min: Optional[float] = None,
        fraud_policy: Optional[str] = None,
        trigger_reason: Optional[str] = None,
        source_classifier_version: Optional[str] = None,
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

        prior_run = await self._run_repo.get_active_run(tenant_id, conversion_id)
        effective_model = model_type or (
            prior_run.get("model_type") if prior_run else None
        ) or "last_touch"
        effective_model_config_id = model_config_id or (
            prior_run.get("model_config_id") if prior_run else None
        )
        prior_snapshot = _json_dict(
            prior_run.get("model_config_snapshot") if prior_run else None
        )
        model_config: dict[str, Any] = {}
        if prior_snapshot and model_type is None and model_config_id is None:
            model_config = prior_snapshot
        elif effective_model_config_id:
            model_config = (
                await self._run_repo.get_model_config(
                    tenant_id, str(effective_model_config_id)
                )
                or {}
            )
            if model_config_id and not model_config:
                raise ValueError(
                    f"Attribution model config {model_config_id} not found for tenant {tenant_id}"
                )
        if model_type is None and model_config.get("model_type"):
            effective_model = str(model_config["model_type"])
        effective_model_version = (
            model_config.get("model_version")
            or (
                prior_run.get("model_version")
                if prior_run and model_type is None
                else None
            )
            or "1.0"
        )
        effective_lookback_hours = int(
            lookback_hours
            if lookback_hours is not None
            else model_config.get("click_lookback_window", 720)
        )
        effective_view_lookback_hours = int(
            view_lookback_hours
            if view_lookback_hours is not None
            else model_config.get("view_lookback_window", 168)
        )
        effective_identity_confidence_min = float(
            identity_confidence_min
            if identity_confidence_min is not None
            else model_config.get("identity_confidence_min", 0.0)
        )
        effective_fraud_policy = str(
            fraud_policy
            if fraud_policy is not None
            else model_config.get("fraud_policy", "exclude")
        )
        effective_direct_policy = str(
            model_config.get("direct_traffic_policy", "include")
        )
        engaged_view_threshold_ms = int(
            model_config.get("engaged_view_threshold_ms", 0)
        )
        model_config_snapshot = {
            **model_config,
            "model_config_id": (
                str(effective_model_config_id) if effective_model_config_id else None
            ),
            "model_type": effective_model,
            "model_version": effective_model_version,
            "click_lookback_window": effective_lookback_hours,
            "view_lookback_window": effective_view_lookback_hours,
            "identity_confidence_min": effective_identity_confidence_min,
            "fraud_policy": effective_fraud_policy,
            "direct_traffic_policy": effective_direct_policy,
            "engaged_view_threshold_ms": engaged_view_threshold_ms,
        }

        # 2. Create pending run
        run = await self._run_repo.create_run({
            "tenant_id": tenant_id,
            "conversion_id": conversion_id,
            "model_type": effective_model,
            "model_version": effective_model_version,
            "code_version": _CODE_VERSION,
            "model_config_id": effective_model_config_id,
            "model_config_snapshot": model_config_snapshot,
            "status": "pending",
            "currency": conversion.get("currency", "USD"),
            "eligible_revenue": conversion.get("net_value") or conversion.get("gross_value"),
            "trigger_reason": trigger_reason or "manual",
            "source_classifier_version": source_classifier_version,
            "prior_attribution_run_id": (
                prior_run.get("attribution_run_id") if prior_run else None
            ),
        })
        run_id = run["attribution_run_id"]

        try:
            await self._run_repo.update_run(run_id, {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }, tenant_id=tenant_id)

            # 3. Load active journey version for the profile
            if conversion.get("profile_id"):
                identity_type = "profile"
                profile_id = conversion.get("profile_id")
            else:
                identity_type = "cluster"
                profile_id = conversion.get("cluster_id")
            journey_versions = []
            touchpoint_ids: list[str] = []
            journey_id: Optional[str] = None
            journey_version_id: Optional[str] = None

            if profile_id:
                journey_versions = await self._journey_repo.find_current_for_profile(
                    tenant_id,
                    profile_id,
                    identity_type=identity_type,
                )
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
            click_cutoff = conversion_ts - timedelta(hours=effective_lookback_hours)
            view_cutoff = conversion_ts - timedelta(hours=effective_view_lookback_hours)

            candidates: list[dict[str, Any]] = []
            if touchpoint_ids:
                for tp_id in touchpoint_ids:
                    tp = await self._touchpoint_repo.get(tenant_id, tp_id)
                    if tp is None:
                        missing_id = str(tp_id)
                        excluded_ids.append(missing_id)
                        exclusion_reasons[missing_id] = "touchpoint_missing"
                        continue
                    candidates.append(tp)
            else:
                # No journey — try to find touchpoints by profile/anonymous_id
                if profile_id:
                    candidates = await self._touchpoint_repo.list_by_profile(
                        tenant_id, profile_id,
                        identity_type=identity_type,
                        before_occurred=conversion_ts,
                        limit=500,
                    )

            for tp in candidates:
                tp_key = str(tp.get("touchpoint_id") or tp.get("idempotency_key") or "")
                exclusion_reason = _touchpoint_exclusion_reason(
                    tp,
                    conversion_ts=conversion_ts,
                    click_cutoff=click_cutoff,
                    view_cutoff=view_cutoff,
                    identity_confidence_min=effective_identity_confidence_min,
                    fraud_policy=effective_fraud_policy,
                    direct_traffic_policy=effective_direct_policy,
                    engaged_view_threshold_ms=engaged_view_threshold_ms,
                )
                if exclusion_reason:
                    if tp_key:
                        excluded_ids.append(tp_key)
                        exclusion_reasons[tp_key] = exclusion_reason
                    continue
                raw_touchpoints.append(tp)

            input_touchpoint_ids = [
                str(tp.get("touchpoint_id"))
                for tp in raw_touchpoints
                if tp.get("touchpoint_id")
            ]
            effective_classifier_version = source_classifier_version or (
                _derive_source_classifier_version(raw_touchpoints)
            )

            # 6. Run attribution model
            result = await _resolver.resolve(
                user_id=profile_id or conversion_id,
                event={
                    "event_type": "conversion",
                    "conversion_id": conversion_id,
                    "conversion_occurred_at": conversion_ts.isoformat(),
                    "timestamp": conversion_ts.isoformat(),
                },
                touchpoints=[_touchpoint_to_resolver_dict(tp) for tp in raw_touchpoints],
                model_name=effective_model,
                # Engine policy already applies click/view-specific cutoffs.
                # Give the resolver the widest effective horizon so it cannot
                # re-cap a configured or snapshotted policy at its 720h default.
                lookback_window_hours=max(
                    effective_lookback_hours,
                    effective_view_lookback_hours,
                ),
            )

            # 7. Build credit rows
            gross_revenue = _to_decimal(conversion.get("gross_value") or "0") or Decimal("0")
            net_revenue = _to_decimal(
                conversion.get("net_value") or conversion.get("gross_value") or "0"
            ) or Decimal("0")
            contribution_value = _to_decimal(
                conversion.get("contribution_value") or "0"
            ) or Decimal("0")

            credit_rows: list[dict[str, Any]] = []
            total_weight = Decimal("0")

            for credit in result.credits:
                weight = Decimal(str(round(credit.weight, 8)))
                total_weight += weight

                # Resolver models retain the canonical id in properties; matching
                # on it prevents same-channel/source touches from borrowing each
                # other's campaign or classification snapshot.
                resolved_tp_id = (credit.touchpoint.properties or {}).get("touchpoint_id")
                tp_meta = _find_touchpoint_by_id(raw_touchpoints, resolved_tp_id)
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
                    "source_class": tp_meta.get("source_class") if tp_meta else None,
                    "referral_mediation_type": tp_meta.get("referral_mediation_type") if tp_meta else None,
                    "ai_provider": tp_meta.get("ai_provider") if tp_meta else None,
                    "ai_product": tp_meta.get("ai_product") if tp_meta else None,
                    "actor_type": tp_meta.get("actor_type") if tp_meta else None,
                    "journey_role": tp_meta.get("journey_role") if tp_meta else None,
                    "evidence_confidence": tp_meta.get("evidence_confidence") if tp_meta else None,
                    "verification_level": tp_meta.get("verification_level") if tp_meta else None,
                    "source_classifier_version": tp_meta.get("source_classifier_version") if tp_meta else None,
                    "normalized_referrer_domain": tp_meta.get("normalized_referrer_domain") if tp_meta else None,
                    "source_classification_id": tp_meta.get("source_classification_id") if tp_meta else None,
                    "attribution_eligible": tp_meta.get("attribution_eligible", True) if tp_meta else True,
                    "verified_referral_link_id": tp_meta.get("verified_referral_link_id") if tp_meta else None,
                    "credit_weight": str(weight),
                    "attributed_conversion_count": str(weight),
                    "attributed_gross_revenue": str(weight * gross_revenue),
                    "attributed_net_revenue": str(weight * net_revenue),
                    "attributed_contribution_value": str(weight * contribution_value),
                    "evidence_ids": [
                        str(tp_meta.get("source_classification_id"))
                    ] if tp_meta and tp_meta.get("source_classification_id") else [],
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

            # 9. Persist credits and switch the active version as one transaction.
            completed_run = await self._run_repo.complete_run_atomically(
                run_id,
                tenant_id,
                conversion_id,
                credit_rows,
                {
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "credit_total": str(total_weight),
                    "unattributed_credit": str(unattributed),
                    "input_touchpoint_ids": input_touchpoint_ids,
                    "excluded_touchpoint_ids": excluded_ids,
                    "exclusion_reasons": exclusion_reasons,
                    "journey_id": journey_id,
                    "journey_version_id": journey_version_id,
                    "trigger_reason": trigger_reason or "manual",
                    "source_classifier_version": effective_classifier_version,
                    "prior_attribution_run_id": (
                        prior_run.get("attribution_run_id") if prior_run else None
                    ),
                },
            )
            if completed_run is None:
                raise RuntimeError(f"Attribution run {run_id} disappeared before completion")

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
            }, tenant_id=tenant_id)
            logger.exception("Attribution failed: run_id=%s conversion=%s", run_id, conversion_id)
            raise

    async def run_backfill(
        self,
        tenant_id: str,
        *,
        start_at: datetime,
        end_at: datetime,
        model_type: str = "last_touch",
        force: bool = False,
    ) -> dict[str, Any]:
        """Run attribution for all unattributed conversions in a time window.

        Returns a summary dict with counts of success/failure.
        """
        from services.measurement.repositories.conversion_repo import ConversionRepository
        conv_repo = ConversionRepository()

        total = 0
        success = 0
        failed = 0
        skipped = 0

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
                # Ordinary backfills retain the existing active result. Explicit
                # repair/reclassification backfills set force=True and always
                # create a new immutable run.
                existing = await self._run_repo.get_active_run(tenant_id, conv_id)
                if existing and existing.get("status") == "complete" and not force:
                    skipped += 1
                    continue
                try:
                    await self.run_for_conversion(
                        tenant_id, conv_id,
                        model_type=model_type,
                        trigger_reason="forced_backfill" if force else "backfill",
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
            "skipped_existing": skipped,
            "force": force,
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
            if conversion.get("profile_id"):
                identity_type = "profile"
                profile_id = conversion.get("profile_id")
            else:
                identity_type = "cluster"
                profile_id = conversion.get("cluster_id")
            raw_touchpoints: list[dict[str, Any]] = []
            if profile_id:
                raw_touchpoints = await self._touchpoint_repo.list_by_profile(
                    tenant_id,
                    profile_id,
                    identity_type=identity_type,
                    limit=500,
                )
            raw_touchpoints = [
                tp for tp in raw_touchpoints
                if _touchpoint_exclusion_reason(
                    tp,
                    conversion_ts=_parse_ts(conversion.get("occurred_at"))
                    or datetime.now(timezone.utc),
                    click_cutoff=datetime.min.replace(tzinfo=timezone.utc),
                    view_cutoff=datetime.min.replace(tzinfo=timezone.utc),
                    identity_confidence_min=0.0,
                    fraud_policy="exclude",
                    direct_traffic_policy="include",
                    engaged_view_threshold_ms=0,
                ) is None
            ]
            conversion_ts = _parse_ts(conversion.get("occurred_at")) or datetime.now(timezone.utc)

            result_a = await _resolver.resolve(
                user_id=profile_id or conv_id,
                event={"event_type": "conversion", "timestamp": conversion_ts.isoformat()},
                touchpoints=[_touchpoint_to_resolver_dict(tp) for tp in raw_touchpoints],
                model_name=model_a,
            )
            result_b = await _resolver.resolve(
                user_id=profile_id or conv_id,
                event={"event_type": "conversion", "timestamp": conversion_ts.isoformat()},
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
    actor_type = tp.get("actor_type")
    if not actor_type:
        if tp.get("agent_id"):
            actor_type = "agent"
        elif tp.get("profile_id") or tp.get("anonymous_id"):
            actor_type = "human"
    return {
        "channel": tp.get("channel", "unknown"),
        "source": tp.get("source", "unknown"),
        "campaign": tp.get("campaign_id", ""),
        "timestamp": tp.get("occurred_at", datetime.now(timezone.utc).isoformat()),
        "event_type": tp.get("touchpoint_type", "page_view"),
        "properties": {
            "touchpoint_id": tp.get("touchpoint_id"),
            "actor_type": actor_type,
            "source_class": tp.get("source_class"),
            "referral_mediation_type": tp.get("referral_mediation_type"),
            "ai_provider": tp.get("ai_provider"),
            "ai_product": tp.get("ai_product"),
            "journey_role": tp.get("journey_role"),
            "evidence_confidence": tp.get("evidence_confidence"),
            "verification_level": tp.get("verification_level"),
            "source_classifier_version": tp.get("source_classifier_version"),
            "normalized_referrer_domain": tp.get("normalized_referrer_domain"),
            "source_classification_id": tp.get("source_classification_id"),
            "attribution_eligible": tp.get("attribution_eligible", True),
            "verified_referral_link_id": tp.get("verified_referral_link_id"),
            "is_view_through": tp.get("is_view_through", False),
            "is_click_through": tp.get("is_click_through", False),
            "is_impression": tp.get("is_view_through", False),
            "dwell_ms": tp.get("dwell_ms"),
            "viewable_dwell_ms": tp.get("dwell_ms"),
        },
    }


def _comms_eligibility(tp: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Comms touchpoint eligibility (ADR-C8): delivery = context only,
    reported opens excluded by default, machine activity excluded, replies
    configurable. Non-comms touchpoints always pass."""
    from services.comms.attribution_policy import comms_touchpoint_eligibility
    return comms_touchpoint_eligibility(tp)


def _build_resolver_touchpoints(raw: list[dict[str, Any]]) -> list[Touchpoint]:
    result = []
    for tp in raw:
        ts = _parse_ts(tp.get("occurred_at")) or datetime.now(timezone.utc)
        # Carry the same immutable identity and source snapshot the resolver
        # receives on the production path.
        props = _touchpoint_to_resolver_dict(tp)["properties"]
        if not props.get("actor_type"):
            if tp.get("agent_id"):
                props["actor_type"] = "agent"
            elif tp.get("profile_id") or tp.get("anonymous_id"):
                props["actor_type"] = "human"
        if tp.get("agent_id"):
            props["agent_id"] = tp["agent_id"]
        if tp.get("wallet_id"):
            props["wallet_id"] = tp["wallet_id"]
        result.append(Touchpoint(
            channel=tp.get("channel", "unknown"),
            source=tp.get("source", "unknown"),
            campaign=tp.get("campaign_id", ""),
            timestamp=ts,
            event_type=tp.get("touchpoint_type", "page_view"),
            properties=props,
        ))
    return result


def _find_touchpoint_by_id(
    touchpoints: list[dict[str, Any]],
    touchpoint_id: Any,
) -> Optional[dict[str, Any]]:
    """Find the exact canonical touchpoint represented by a model credit."""
    if touchpoint_id is None:
        return None
    expected = str(touchpoint_id)
    return next(
        (tp for tp in touchpoints if str(tp.get("touchpoint_id")) == expected),
        None,
    )


def _touchpoint_exclusion_reason(
    tp: dict[str, Any],
    *,
    conversion_ts: datetime,
    click_cutoff: datetime,
    view_cutoff: datetime,
    identity_confidence_min: float,
    fraud_policy: str,
    direct_traffic_policy: str,
    engaged_view_threshold_ms: int,
) -> Optional[str]:
    eligibility = tp.get("attribution_eligible", True)
    explicitly_ineligible = eligibility is False or (
        isinstance(eligibility, str)
        and eligibility.strip().lower() in {"false", "0", "no"}
    )
    if explicitly_ineligible:
        return "source_not_attribution_eligible"
    if tp.get("journey_role") == "excluded":
        return "source_journey_role_excluded"
    if direct_traffic_policy == "exclude" and (
        # Legacy rows say "direct"; the canonical vocabulary says
        # "direct_unknown". Both mean the same absence of source evidence.
        tp.get("source_class") in ("direct", "direct_unknown")
        or tp.get("referral_mediation_type") == "direct_entry"
    ):
        return "direct_traffic_policy"
    if fraud_policy == "exclude" and (
        tp.get("suspected_fraud") is True
        or tp.get("is_fraud") is True
        or str(tp.get("fraud_status") or "").lower()
        in {"suspected", "confirmed", "fraudulent", "blocked"}
    ):
        return "fraud_policy"

    tp_ts = _parse_ts(tp.get("occurred_at"))
    if tp_ts is None:
        return "missing_timestamp"
    if tp_ts > conversion_ts:
        return "after_conversion"
    cutoff = view_cutoff if tp.get("is_view_through", False) else click_cutoff
    if tp_ts < cutoff:
        return "outside_lookback"
    if tp.get("is_view_through", False) and engaged_view_threshold_ms > 0:
        dwell_ms = int(tp.get("dwell_ms") or 0)
        if dwell_ms < engaged_view_threshold_ms:
            return "view_engagement_threshold"

    if identity_confidence_min > 0.0:
        confidence = tp.get("identity_confidence")
        if confidence is not None and float(confidence) < identity_confidence_min:
            return "low_identity_confidence"

    eligible, reason = _comms_eligibility(tp)
    if not eligible:
        return reason or "comms_policy"
    return None


def _derive_source_classifier_version(touchpoints: list[dict[str, Any]]) -> Optional[str]:
    versions = {
        str(tp.get("source_classifier_version"))
        for tp in touchpoints
        if tp.get("source_classifier_version")
    }
    if not versions:
        return None
    if len(versions) == 1:
        return next(iter(versions))
    return "mixed"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


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
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
