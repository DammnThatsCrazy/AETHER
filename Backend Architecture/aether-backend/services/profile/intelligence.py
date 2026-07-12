"""
Profile 360 Intelligence Aggregator.

Implements the 14 intelligence extension endpoints that were previously stubs:
    /tier, /asset-composition, /pnl, /trading-profile, /location-history,
    /temporal-heatmap, /social-intelligence, /journey-economics,
    /device-performance, /funnel, /time-to-convert, /retarget-recommendations,
    /web2, /protocol-metrics, /governance-activity

Each method queries the appropriate Gold-tier repository and shapes the result
into the standard SubResourceEnvelope.  When the gold tier has no data for an
entity (e.g. the ETL pipeline hasn't run yet) the method returns an empty but
correctly-shaped response rather than 500-ing.  Consent enforcement is applied
in-band for the /web2 endpoint.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from services.policy import consent_policy_engine

# Lazy type alias — avoid module-level lake/repos imports so tests can import
# this module without needing FastAPI installed.
GoldRepository = None  # resolved at runtime inside __init__

logger = get_logger("aether.profile.intelligence")

_WINDOW_DAYS: dict[str, Optional[int]] = {
    "30d": 30,
    "60d": 60,
    "90d": 90,
    "lifetime": None,
}


def _window_cutoff(window: str) -> Optional[str]:
    days = _WINDOW_DAYS.get(window)
    if days is None:
        return None
    return (utc_now() - timedelta(days=days)).isoformat()


def _in_window(record: dict, cutoff: Optional[str]) -> bool:
    if cutoff is None:
        return True
    ts = record.get("materialized_at") or record.get("updated_at") or record.get("created_at") or ""
    return ts >= cutoff


def _tenant_ok(record: dict, tenant_id: str) -> bool:
    t = record.get("tenant_id")
    return t in (None, "", tenant_id)


def _filter(rows: list[dict], tenant_id: str, cutoff: Optional[str]) -> list[dict]:
    return [r for r in rows if _tenant_ok(r, tenant_id) and _in_window(r, cutoff)]


def _envelope(
    entity_id: str,
    tenant_id: str,
    kind: str,
    window: str,
    items: list,
    summary: dict,
    sources: list[str],
    *,
    limit: Optional[int] = None,
) -> dict:
    result: dict[str, Any] = {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "kind": kind,
        "window": window,
        "items": items,
        "summary": summary,
        "computed_at": utc_now().isoformat(),
        "provenance": {"sources": sources},
    }
    if limit is not None:
        result["pagination"] = {
            "limit": limit,
            "count": len(items),
            "has_more": len(items) >= limit,
        }
    return result


async def _safe(label: str, coro):
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "intelligence_dimension_failed",
            extra={"dimension": label, "error": str(exc)},
        )
        return []


def _val(r: dict) -> Any:
    return r.get("value") or {}


def _dims(r: dict) -> dict:
    return r.get("dimensions") or {}


def _shape(r: dict, **fallback_fields) -> dict:
    v = _val(r)
    if isinstance(v, dict) and v:
        return {**v, "computed_at": r.get("materialized_at")}
    d = _dims(r)
    return {**fallback_fields, **{k: d.get(k) for k in fallback_fields}, "computed_at": r.get("materialized_at")}


class IntelligenceAggregator:
    """Aggregator for the Profile 360 intelligence extension endpoints.

    Queries Gold-tier repositories and applies window-based filtering on
    ``materialized_at``.  All methods return the standard SubResourceEnvelope.
    """

    def __init__(
        self,
        *,
        entity_tiers_repo=None,
        asset_composition_repo=None,
        pnl_repo=None,
        trading_profile_repo=None,
        location_history_repo=None,
        temporal_heatmap_repo=None,
        social_intelligence_repo=None,
        journey_economics_repo=None,
        ad_spend_repo=None,
        credit_signals_repo=None,
        tradfi_portfolio_repo=None,
        web3_daily_metrics_repo=None,
        governance_repo=None,
        consent_repo=None,
    ) -> None:
        # Lazy-import lake/repos so callers that inject their own collaborators
        # (e.g. tests) don't need FastAPI installed.
        if any(r is None for r in (
            entity_tiers_repo, asset_composition_repo, pnl_repo,
            trading_profile_repo, location_history_repo, temporal_heatmap_repo,
            social_intelligence_repo, journey_economics_repo, ad_spend_repo,
            credit_signals_repo, tradfi_portfolio_repo, web3_daily_metrics_repo,
            governance_repo,
        )):
            from repositories.lake import (
                gold_ad_spend as _gad,
                gold_asset_composition as _gac,
                gold_credit_signals as _gcs,
                gold_entity_pnl as _gpnl,
                gold_entity_tiers as _gt,
                gold_governance as _gg,
                gold_journey_economics as _gje,
                gold_location_history as _glh,
                gold_social_intelligence as _gsi,
                gold_temporal_heatmap as _gth,
                gold_tradfi_portfolio as _gtp,
                gold_trading_profile as _gtrp,
                gold_web3_daily_metrics as _gwdm,
            )
        else:
            _gt = _gac = _gpnl = _gtrp = _glh = _gth = _gsi = _gje = _gad = _gcs = _gtp = _gwdm = _gg = None  # type: ignore[assignment]

        if consent_repo is None:
            from repositories.repos import ConsentRepository
            consent_repo = ConsentRepository()

        self._tiers = entity_tiers_repo if entity_tiers_repo is not None else _gt
        self._asset_composition = asset_composition_repo if asset_composition_repo is not None else _gac
        self._pnl = pnl_repo if pnl_repo is not None else _gpnl
        self._trading_profile = trading_profile_repo if trading_profile_repo is not None else _gtrp
        self._location_history = location_history_repo if location_history_repo is not None else _glh
        self._temporal_heatmap = temporal_heatmap_repo if temporal_heatmap_repo is not None else _gth
        self._social = social_intelligence_repo if social_intelligence_repo is not None else _gsi
        self._journey_econ = journey_economics_repo if journey_economics_repo is not None else _gje
        self._ad_spend = ad_spend_repo if ad_spend_repo is not None else _gad
        self._credit_signals = credit_signals_repo if credit_signals_repo is not None else _gcs
        self._tradfi_portfolio = tradfi_portfolio_repo if tradfi_portfolio_repo is not None else _gtp
        self._web3_metrics = web3_daily_metrics_repo if web3_daily_metrics_repo is not None else _gwdm
        self._governance = governance_repo if governance_repo is not None else _gg
        self._consent = consent_repo

    async def tier(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Entity tier (Whale/Shark/Dolphin/Fish/Shrimp) + percentile rank."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("tier", self._tiers.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            items.append({
                "tier": (v.get("tier") if isinstance(v, dict) else str(v)) or d.get("tier"),
                "percentile": d.get("percentile"),
                "score": d.get("score"),
                "population_size": d.get("population_size"),
                "computed_at": r.get("materialized_at"),
            })
        summary = {
            "tier": items[0].get("tier") if items else None,
            "percentile": items[0].get("percentile") if items else None,
        }
        return _envelope(entity_id, tenant_id, "tier", window, items, summary, ["gold_entity_tiers"])

    async def asset_composition(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """On-chain portfolio composition by asset category."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("asset_composition", self._asset_composition.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        total_value = 0.0
        for r in rows:
            v, d = _val(r), _dims(r)
            usd = d.get("value_usd") or (v if isinstance(v, (int, float)) else 0)
            try:
                total_value += float(usd)
            except (TypeError, ValueError):
                pass
            items.append({
                "category": d.get("category") or (r.get("metric_name", "").split(":")[-1] if r.get("metric_name") else None),
                "value_usd": usd,
                "percentage": d.get("percentage"),
                "top_assets": d.get("top_assets") or [],
                "computed_at": r.get("materialized_at"),
            })
        for item in items:
            if item["percentage"] is None and total_value > 0:
                try:
                    item["percentage"] = round(float(item["value_usd"]) / total_value, 4)
                except (TypeError, ValueError):
                    pass
        summary = {"total_value_usd": total_value, "category_count": len(items)}
        return _envelope(entity_id, tenant_id, "asset_composition", window, items, summary, ["gold_asset_composition", "moralis"])

    async def pnl(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Realized + unrealized PNL and TVL delta."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("pnl", self._pnl.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "realized_pnl": d.get("realized_pnl"),
                    "unrealized_pnl": d.get("unrealized_pnl"),
                    "tvl_delta": d.get("tvl_delta"),
                    "cost_basis_method": d.get("cost_basis_method", "fifo"),
                    "computed_at": r.get("materialized_at"),
                })
        total_realized = sum(float(i.get("realized_pnl") or 0) for i in items)
        total_unrealized = sum(float(i.get("unrealized_pnl") or 0) for i in items)
        summary = {"total_realized_pnl": total_realized, "total_unrealized_pnl": total_unrealized}
        return _envelope(entity_id, tenant_id, "pnl", window, items, summary, ["gold_entity_pnl", "silver_web3_events", "coingecko"])

    async def trading_profile(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """On-chain trading behavior: favorite pairs, protocol loyalty, gas strategy."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("trading_profile", self._trading_profile.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "favorite_pairs": d.get("favorite_pairs") or [],
                    "protocol_loyalty": d.get("protocol_loyalty") or {},
                    "gas_strategy": d.get("gas_strategy") or {},
                    "avg_slippage": d.get("avg_slippage"),
                    "trade_count": d.get("trade_count"),
                    "computed_at": r.get("materialized_at"),
                })
        summary = {
            "trade_count": sum(int(i.get("trade_count") or 0) for i in items),
            "profile_computed": len(items) > 0,
        }
        return _envelope(entity_id, tenant_id, "trading_profile", window, items, summary, ["gold_trading_profile", "silver_web3_events"])

    async def location_history(self, entity_id: str, tenant_id: str, window: str = "30d", limit: int = 20) -> dict:
        """City-level location history with classification."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("location_history", self._location_history.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "city": d.get("city"),
                    "country": d.get("country"),
                    "region": d.get("region"),
                    "classification": d.get("classification", "unknown"),
                    "session_count": d.get("session_count"),
                    "first_seen": d.get("first_seen"),
                    "last_seen": d.get("last_seen"),
                    "computed_at": r.get("materialized_at"),
                })
        items = items[:limit]
        primary = next((i.get("city") for i in items if i.get("classification") == "primary"), None)
        summary = {"location_count": len(items), "primary_location": primary}
        return _envelope(entity_id, tenant_id, "location_history", window, items, summary, ["gold_location_history"], limit=limit)

    async def temporal_heatmap(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """24x7 activity density matrix + streak data."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("temporal_heatmap", self._temporal_heatmap.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "day_of_week": d.get("day_of_week"),
                    "hour_utc": d.get("hour_utc"),
                    "activity_count": d.get("activity_count", 0),
                    "timezone": d.get("timezone", "UTC"),
                    "streak_days": d.get("streak_days"),
                    "computed_at": r.get("materialized_at"),
                })
        peak_hour = max(items, key=lambda x: x.get("activity_count") or 0).get("hour_utc") if items else None
        summary = {"data_points": len(items), "peak_hour_utc": peak_hour}
        return _envelope(entity_id, tenant_id, "temporal_heatmap", window, items, summary, ["gold_temporal_heatmap"])

    async def social_intelligence(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Cross-platform social aggregation."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("social_intelligence", self._social.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "platform": d.get("platform"),
                    "handle": d.get("handle"),
                    "followers": d.get("followers"),
                    "following": d.get("following"),
                    "post_count": d.get("post_count") or d.get("posts"),
                    "engagement_rate": d.get("engagement_rate"),
                    "verified": d.get("verified", False),
                    "computed_at": r.get("materialized_at"),
                })
        platforms = [i.get("platform") for i in items if i.get("platform")]
        summary = {"platform_count": len(items), "platforms": platforms}
        return _envelope(entity_id, tenant_id, "social_intelligence", window, items, summary, ["gold_social_intelligence", "twitter", "farcaster", "lens", "discord", "github"])

    async def journey_economics(self, entity_id: str, tenant_id: str, window: str = "30d", limit: int = 20) -> dict:
        """Per-journey ROAS, CPA, LTV, and retarget score."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("journey_economics", self._journey_econ.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "journey_id": d.get("journey_id"),
                    "roas": d.get("roas"),
                    "cpa": d.get("cpa"),
                    "ltv": d.get("ltv"),
                    "retarget_score": d.get("retarget_score"),
                    "campaign_id": d.get("campaign_id"),
                    "computed_at": r.get("materialized_at"),
                })
        items = items[:limit]
        roas_values = [float(i["roas"]) for i in items if i.get("roas") is not None]
        avg_roas = round(sum(roas_values) / len(roas_values), 4) if roas_values else None
        summary = {"journey_count": len(items), "avg_roas": avg_roas}
        return _envelope(entity_id, tenant_id, "journey_economics", window, items, summary, ["gold_journey_economics", "gold_ad_spend"], limit=limit)

    async def device_performance(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Conversion rate and average conversion value per device type."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("device_performance", self._journey_econ.get_metrics(entity_id)), tenant_id, cutoff)
        device_stats: dict[str, dict] = {}
        for r in rows:
            d = _dims(r)
            device = d.get("device_type") or d.get("device")
            if not device:
                continue
            slot = device_stats.setdefault(device, {"conversions": 0, "total": 0, "values": []})
            slot["total"] += 1
            if d.get("converted"):
                slot["conversions"] += 1
            cv = d.get("conversion_value")
            if cv is not None:
                try:
                    slot["values"].append(float(cv))
                except (TypeError, ValueError):
                    pass
        items = []
        for device, s in device_stats.items():
            avg_val = round(sum(s["values"]) / len(s["values"]), 4) if s["values"] else None
            items.append({
                "device_type": device,
                "conversion_rate": round(s["conversions"] / s["total"], 4) if s["total"] > 0 else 0.0,
                "avg_conversion_value": avg_val,
                "sample_size": s["total"],
            })
        items.sort(key=lambda x: x["conversion_rate"], reverse=True)
        summary = {"device_count": len(items)}
        return _envelope(entity_id, tenant_id, "device_performance", window, items, summary, ["gold_journey_economics", "event_extension"])

    async def funnel(
        self,
        entity_id: str,
        tenant_id: str,
        window: str = "30d",
        campaign_id: Optional[str] = None,
    ) -> dict:
        """Staged conversion funnel: Impression → Click → Visit → Connect → Swap → Liquidity."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("funnel", self._journey_econ.get_metrics(entity_id)), tenant_id, cutoff)
        if campaign_id:
            rows = [r for r in rows if _dims(r).get("campaign_id") == campaign_id]
        stage_order = ["Impression", "Click", "Visit", "Connect", "Swap", "Liquidity"]
        stage_counts: dict[str, int] = {s: 0 for s in stage_order}
        for r in rows:
            d = _dims(r)
            stage = d.get("funnel_stage") or d.get("stage")
            if stage in stage_counts:
                stage_counts[stage] += 1
        items = []
        prev_count: Optional[int] = None
        for stage in stage_order:
            count = stage_counts[stage]
            conversion_rate = round(count / prev_count, 4) if (prev_count and prev_count > 0 and count > 0) else None
            items.append({"stage": stage, "count": count, "conversion_rate": conversion_rate})
            if count > 0:
                prev_count = count
        active = [i for i in items if i["count"] > 0]
        summary = {"stages_with_data": len(active), "top_stage_count": max((i["count"] for i in items), default=0)}
        return _envelope(entity_id, tenant_id, "funnel", window, items, summary, ["gold_journey_economics", "event_extension"])

    async def time_to_convert(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Median time between each funnel stage conversion."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("time_to_convert", self._journey_econ.get_metrics(entity_id)), tenant_id, cutoff)
        stage_times: dict[str, list[float]] = {}
        for r in rows:
            d = _dims(r)
            from_stage = d.get("from_stage")
            to_stage = d.get("to_stage")
            seconds = d.get("time_seconds")
            if from_stage and to_stage and seconds is not None:
                key = f"{from_stage}->{to_stage}"
                try:
                    stage_times.setdefault(key, []).append(float(seconds))
                except (TypeError, ValueError):
                    pass
        items = []
        for key, times in stage_times.items():
            from_stage, to_stage = key.split("->", 1)
            sorted_times = sorted(times)
            n = len(sorted_times)
            median = sorted_times[n // 2] if n else None
            p90 = sorted_times[int(n * 0.9)] if n else None
            items.append({
                "from_stage": from_stage,
                "to_stage": to_stage,
                "median_seconds": median,
                "p90_seconds": p90,
                "sample_size": n,
            })
        summary = {"transition_count": len(items)}
        return _envelope(entity_id, tenant_id, "time_to_convert", window, items, summary, ["gold_journey_economics"])

    async def retarget_recommendations(
        self,
        entity_id: str,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """Pending and historical retargeting recommendations for analyst review."""
        rows = _filter(await _safe("retarget_recs", self._journey_econ.get_metrics(entity_id)), tenant_id, None)
        items = []
        for r in rows:
            d = _dims(r)
            score = d.get("retarget_score")
            if score is None:
                continue
            rec_status = d.get("retarget_status", "pending")
            if status and rec_status != status:
                continue
            items.append({
                "recommendation_id": r.get("id") or r.get("metric_name"),
                "type": d.get("recommendation_type", "retarget"),
                "reason": d.get("reason"),
                "status": rec_status,
                "score": score,
                "campaign_id": d.get("campaign_id"),
                "journey_id": d.get("journey_id"),
                "computed_at": r.get("materialized_at"),
            })
        items.sort(key=lambda x: x.get("score") or 0, reverse=True)
        items = items[:limit]
        summary = {"total": len(items), "by_status": dict(Counter(i["status"] for i in items))}
        return _envelope(entity_id, tenant_id, "retarget_recommendations", "all", items, summary, ["retarget_recommendations"], limit=limit)

    async def web2(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """TradFi portfolio, bank accounts, credit signals (requires 'credit' consent)."""
        consent = await _safe("web2.consent", self._consent.get_consent(tenant_id, entity_id))
        grants: list[str] = []
        snapshot_id = None
        if isinstance(consent, dict):
            grants = list(consent.get("granted_purposes") or consent.get("purposes") or [])
            if consent.get("credit_consent") is True and "credit" not in grants:
                grants.append("credit")
            snapshot_id = consent.get("snapshot_id")

        # Central consent PolicyDecision — records explainable evidence
        # (policy_decision_id) for this sensitive credit-surface access. The gate
        # behavior is unchanged; the decision is additive.
        decision = await _safe("web2.policy", consent_policy_engine.decide(
            tenant_id=tenant_id, actor_id=tenant_id, action="render_profile360",
            resource_type="profile360.web2", resource_id=entity_id, subject_ref=entity_id,
            purpose="credit", granted_purposes=grants, consent_snapshot_id=snapshot_id,
            redactable_fields=["credit_signals", "tradfi_portfolio", "bank_accounts"],
        ))
        policy_decision_id = getattr(decision, "policy_decision_id", None)
        has_consent = bool(getattr(decision, "allowed", "credit" in grants))
        if not has_consent:
            return _envelope(
                entity_id, tenant_id, "web2", window, [],
                {"consent_required": True, "granted": False,
                 "policy_decision_id": policy_decision_id,
                 "redacted_fields": getattr(decision, "redacted_fields", [])},
                ["plaid", "gold_credit_signals", "gold_tradfi_portfolio"],
            )

        cutoff = _window_cutoff(window)
        tradfi_rows, credit_rows = await asyncio.gather(
            _safe("web2.tradfi", self._tradfi_portfolio.get_metrics(entity_id)),
            _safe("web2.credit", self._credit_signals.get_metrics(entity_id)),
        )
        tradfi_rows = _filter(tradfi_rows, tenant_id, cutoff)
        credit_rows = _filter(credit_rows, tenant_id, cutoff)
        items = []
        for r in tradfi_rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({"data_type": "tradfi", **v, "computed_at": r.get("materialized_at")})
            else:
                items.append({"data_type": "tradfi", "account_type": d.get("account_type"), "balance_usd": d.get("balance_usd"), "institution": d.get("institution"), "computed_at": r.get("materialized_at")})
        for r in credit_rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({"data_type": "credit", **v, "computed_at": r.get("materialized_at")})
            else:
                items.append({"data_type": "credit", "credit_score": d.get("credit_score"), "bureau": d.get("bureau"), "computed_at": r.get("materialized_at")})
        summary = {
            "tradfi_accounts": sum(1 for i in items if i.get("data_type") == "tradfi"),
            "credit_signals": sum(1 for i in items if i.get("data_type") == "credit"),
            "consent_granted": True,
            "policy_decision_id": policy_decision_id,
        }
        return _envelope(entity_id, tenant_id, "web2", window, items, summary, ["plaid", "gold_credit_signals", "gold_tradfi_portfolio"])

    async def protocol_metrics(self, entity_id: str, tenant_id: str, window: str = "30d") -> dict:
        """Protocol TVL history, volume, and fee revenue."""
        cutoff = _window_cutoff(window)
        rows = _filter(await _safe("protocol_metrics", self._web3_metrics.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "date": d.get("date"),
                    "tvl_usd": d.get("tvl_usd"),
                    "volume_usd": d.get("volume_usd"),
                    "fee_revenue_usd": d.get("fee_revenue_usd"),
                    "unique_users": d.get("unique_users"),
                    "computed_at": r.get("materialized_at"),
                })
        items.sort(key=lambda x: x.get("date") or "", reverse=True)
        tvl_values = [float(i["tvl_usd"]) for i in items if i.get("tvl_usd") is not None]
        avg_tvl = round(sum(tvl_values) / len(tvl_values), 2) if tvl_values else None
        summary = {"data_days": len(items), "avg_tvl_usd": avg_tvl}
        return _envelope(entity_id, tenant_id, "protocol_metrics", window, items, summary, ["defillama", "gold_web3_daily_metrics"])

    async def governance_activity(
        self,
        entity_id: str,
        tenant_id: str,
        window: str = "30d",
        limit: int = 20,
    ) -> dict:
        """Governance proposals, votes, and participation rate."""
        cutoff = _window_cutoff(window)
        all_rows = _filter(await _safe("governance_activity", self._governance.get_metrics(entity_id)), tenant_id, cutoff)
        items = []
        for r in all_rows:
            v, d = _val(r), _dims(r)
            if isinstance(v, dict) and v:
                items.append({**v, "computed_at": r.get("materialized_at")})
            else:
                items.append({
                    "proposal_id": d.get("proposal_id"),
                    "vote": d.get("vote"),
                    "voting_power": d.get("voting_power"),
                    "outcome": d.get("outcome"),
                    "protocol": d.get("protocol"),
                    "voted_at": d.get("voted_at"),
                    "computed_at": r.get("materialized_at"),
                })
        items = items[:limit]
        votes_for = sum(1 for i in items if i.get("vote") in ("for", "yes", "1", True))
        votes_against = sum(1 for i in items if i.get("vote") in ("against", "no", "0", False))
        participation_rate = round(len(items) / max(1, len(all_rows)), 4)
        summary = {
            "proposal_count": len(items),
            "votes_for": votes_for,
            "votes_against": votes_against,
            "participation_rate": participation_rate,
        }
        return _envelope(entity_id, tenant_id, "governance_activity", window, items, summary, ["snapshot", "silver_web3_events"], limit=limit)
