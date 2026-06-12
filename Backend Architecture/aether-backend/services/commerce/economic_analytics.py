"""
Aether Service — Commerce Economic Analytics
Aggregates from settlement events, facilitator records, and the commerce store
to produce: service revenue, cluster spend, treasury balance, and facilitator
performance views.

All queries are tenant-scoped. Window filtering uses ISO-8601 period strings
("7d", "30d", "90d", "all").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.service.commerce.analytics")

_SETTLED_STATUSES = {"settled", "paid", "success", "access_granted"}


def _parse_window(period: str) -> Optional[datetime]:
    """Return the earliest datetime for the given window string, or None for 'all'."""
    period = period.lower().strip()
    now = datetime.now(timezone.utc)
    if period in ("all", ""):
        return None
    if period.endswith("d"):
        try:
            days = int(period[:-1])
            return now - timedelta(days=days)
        except ValueError:
            pass
    return None


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


class CommerceEconomicAnalytics:
    """
    Provides cross-cutting economic analytics for the commerce layer.
    Reads from SettlementEventRepository, FacilitatorRepository, and
    the x402 CommerceStore (treasury).
    """

    def __init__(
        self,
        settlements=None,
        facilitators=None,
    ):
        from repositories.repos import SettlementEventRepository, FacilitatorRepository
        self._settlements = settlements or SettlementEventRepository()
        self._facilitators = facilitators or FacilitatorRepository()

    # ── Service Revenue ───────────────────────────────────────────────────────

    async def service_revenue(
        self, service_id: str, tenant_id: str, period: str = "30d"
    ) -> dict:
        """
        Aggregate settled spend for a service_id within the given time window.
        service_id maps to the `provider` field on settlement events.
        """
        cutoff = _parse_window(period)
        rows = await self._settlements.find_many(
            filters={"tenant_id": tenant_id, "provider": service_id},
            limit=10000,
        )
        settled = [
            r for r in rows
            if r.get("status") in _SETTLED_STATUSES
            and (cutoff is None or r.get("occurred_at", "") >= cutoff.isoformat())
        ]
        by_currency: dict[str, Decimal] = {}
        for r in settled:
            cur = r.get("currency", "USDC")
            by_currency[cur] = by_currency.get(cur, Decimal("0")) + _decimal(r.get("amount"))

        return {
            "service_id": service_id,
            "tenant_id": tenant_id,
            "period": period,
            "settled_count": len(settled),
            "revenue_by_currency": {k: str(v) for k, v in by_currency.items()},
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Cluster Spend ─────────────────────────────────────────────────────────

    async def cluster_spend(
        self, cluster_id: str, tenant_id: str, period: str = "30d"
    ) -> dict:
        """
        Aggregate settled spend attributed to a cluster_id.
        cluster_id is stored in settlement event metadata under 'cluster_id'.
        """
        cutoff = _parse_window(period)
        rows = await self._settlements.find_many(
            filters={"tenant_id": tenant_id},
            limit=10000,
        )
        matching = [
            r for r in rows
            if r.get("status") in _SETTLED_STATUSES
            and (r.get("metadata") or {}).get("cluster_id") == cluster_id
            and (cutoff is None or r.get("occurred_at", "") >= cutoff.isoformat())
        ]
        by_currency: dict[str, Decimal] = {}
        agent_ids: set[str] = set()
        for r in matching:
            cur = r.get("currency", "USDC")
            by_currency[cur] = by_currency.get(cur, Decimal("0")) + _decimal(r.get("amount"))
            if r.get("agent_id"):
                agent_ids.add(r["agent_id"])

        return {
            "cluster_id": cluster_id,
            "tenant_id": tenant_id,
            "period": period,
            "settled_count": len(matching),
            "unique_agents": len(agent_ids),
            "spend_by_currency": {k: str(v) for k, v in by_currency.items()},
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Treasury Balance ──────────────────────────────────────────────────────

    async def treasury_balance(self, tenant_id: str) -> dict:
        """
        Return treasury balance and compute 30-day spend runway.
        Balance is read from the CommerceStore treasury; runway is derived
        from the last 30 days of settled spend rate.
        """
        try:
            from services.x402.commerce_store import get_commerce_store
            store = get_commerce_store()
            treasury = await store.get_treasury(tenant_id)
            balance_usd = float(treasury.balance_usd) if treasury else 0.0
            preferred_chains = treasury.preferred_chains if treasury else []
            preferred_assets = treasury.preferred_assets if treasury else []
        except Exception as e:
            logger.warning(f"treasury read failed for {tenant_id}: {e}")
            balance_usd = 0.0
            preferred_chains = []
            preferred_assets = []

        # 30-day spend rate for runway estimate
        cutoff = _parse_window("30d")
        rows = await self._settlements.find_many(
            filters={"tenant_id": tenant_id},
            limit=10000,
        )
        settled_30d = [
            r for r in rows
            if r.get("status") in _SETTLED_STATUSES
            and (cutoff is None or r.get("occurred_at", "") >= cutoff.isoformat())
        ]
        spend_30d_usd = sum(
            float(_decimal(r.get("amount")))
            for r in settled_30d
            if r.get("currency") in ("USDC", "USD")
        )
        daily_rate = spend_30d_usd / 30.0 if spend_30d_usd else 0.0
        runway_days = int(balance_usd / daily_rate) if daily_rate > 0 else None

        return {
            "tenant_id": tenant_id,
            "balance_usd": balance_usd,
            "preferred_chains": preferred_chains,
            "preferred_assets": preferred_assets,
            "spend_last_30d_usd": round(spend_30d_usd, 6),
            "daily_spend_rate_usd": round(daily_rate, 6),
            "runway_days": runway_days,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Facilitator Performance ───────────────────────────────────────────────

    async def facilitator_performance(
        self, tenant_id: str, period: str = "30d"
    ) -> dict:
        """
        Per-facilitator performance matrix: transaction count, success rate,
        total volume, and average latency (where available).
        """
        cutoff = _parse_window(period)
        rows = await self._settlements.find_many(
            filters={"tenant_id": tenant_id},
            limit=10000,
        )
        if cutoff:
            rows = [r for r in rows if r.get("occurred_at", "") >= cutoff.isoformat()]

        # Aggregate by facilitator_id
        stats: dict[str, dict] = {}
        for r in rows:
            fid = r.get("facilitator_id") or r.get("provider") or "unknown"
            if fid not in stats:
                stats[fid] = {"total": 0, "settled": 0, "failed": 0, "volume": Decimal("0")}
            stats[fid]["total"] += 1
            status = r.get("status", "")
            if status in _SETTLED_STATUSES:
                stats[fid]["settled"] += 1
                stats[fid]["volume"] += _decimal(r.get("amount"))
            elif status in ("failed", "error"):
                stats[fid]["failed"] += 1

        facilitators_list = []
        for fid, s in stats.items():
            total = s["total"]
            success_rate = round(s["settled"] / total, 4) if total > 0 else 0.0
            facilitators_list.append({
                "facilitator_id": fid,
                "transaction_count": total,
                "settled_count": s["settled"],
                "failed_count": s["failed"],
                "success_rate": success_rate,
                "total_volume_usd": str(s["volume"]),
            })

        # Sort by volume desc
        facilitators_list.sort(
            key=lambda x: Decimal(x["total_volume_usd"]), reverse=True
        )

        return {
            "tenant_id": tenant_id,
            "period": period,
            "facilitators": facilitators_list,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
