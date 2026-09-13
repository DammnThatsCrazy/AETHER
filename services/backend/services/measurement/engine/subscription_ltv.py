"""Subscription LTV attribution — links renewal revenue to acquisition touchpoints.

For subscription products, each renewal conversion inherits attribution from the
original acquisition event. The acquisition touchpoints are identified by finding
the earliest conversion that shares the same subscription_id (or profile_id +
first conversion_type=subscription_started).

LTV is the cumulative net_value across all conversions in a subscription lifecycle:
  subscription_started → subscription_renewed × N → subscription_cancelled

Attribution credits for renewals do NOT run the full attribution engine against new
touchpoints — there may be no new touchpoints. Instead renewal credits are derived
from the active credits on the original acquisition run, preserving the same
channel/source weights so that ROI attribution remains consistent across the
full customer lifetime.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import ConversionRepository

logger = logging.getLogger("aether.measurement.subscription_ltv")

_ACQUISITION_TYPES = frozenset({
    "subscription_started",
    "trial_started",
    "trial_converted",
})

_RENEWAL_TYPES = frozenset({
    "subscription_renewed",
    "invoice_paid",
})

_TERMINAL_TYPES = frozenset({
    "subscription_cancelled",
    "subscription_churned",
})


class SubscriptionLTVService:
    """Compute and attribute subscription lifetime value.

    Usage:
        service = SubscriptionLTVService()
        ltv = await service.compute_ltv(tenant_id, subscription_id)
        run = await service.attribute_renewal(tenant_id, renewal_conversion_id)
    """

    def __init__(self) -> None:
        self._conv_repo = ConversionRepository()
        self._run_repo = AttributionRunRepository()

    async def compute_ltv(
        self,
        tenant_id: str,
        subscription_id: str,
        *,
        include_pending: bool = False,
    ) -> dict[str, Any]:
        """Return cumulative LTV metrics for a subscription.

        Returns:
            {
                subscription_id, tenant_id,
                acquisition_conversion_id,
                profile_id,
                total_gross_value, total_net_value, total_refunds,
                currency,
                conversion_count, renewal_count, status,
                first_conversion_at, latest_conversion_at,
                is_active,
            }
        """
        conversions = await self._load_subscription_conversions(tenant_id, subscription_id)
        if not conversions:
            return {
                "subscription_id": subscription_id,
                "tenant_id": tenant_id,
                "error": "no_conversions_found",
                "total_gross_value": "0",
                "total_net_value": "0",
                "conversion_count": 0,
            }

        gross = Decimal("0")
        net = Decimal("0")
        refunds = Decimal("0")
        renewal_count = 0
        acquisition_id: Optional[str] = None
        profile_id: Optional[str] = None
        currency = "USD"
        first_at: Optional[str] = None
        latest_at: Optional[str] = None
        is_active = True

        for conv in conversions:
            if not include_pending and conv.get("conversion_status") not in ("confirmed", "adjusted"):
                continue

            ct = conv.get("conversion_type", "")
            gross += _to_decimal(conv.get("gross_value")) or Decimal("0")
            net += _to_decimal(conv.get("net_value")) or Decimal("0")
            refunds += _to_decimal(conv.get("refund_value")) or Decimal("0")
            currency = conv.get("currency", currency)

            oc = conv.get("occurred_at", "")
            if oc and (first_at is None or oc < first_at):
                first_at = oc
            if oc and (latest_at is None or oc > latest_at):
                latest_at = oc

            if ct in _ACQUISITION_TYPES and acquisition_id is None:
                acquisition_id = conv.get("conversion_id")
                profile_id = conv.get("profile_id") or conv.get("cluster_id")

            if ct in _RENEWAL_TYPES:
                renewal_count += 1

            if ct in _TERMINAL_TYPES:
                is_active = False

        return {
            "subscription_id": subscription_id,
            "tenant_id": tenant_id,
            "acquisition_conversion_id": acquisition_id,
            "profile_id": profile_id,
            "total_gross_value": str(gross),
            "total_net_value": str(net),
            "total_refunds": str(refunds),
            "currency": currency,
            "conversion_count": len(conversions),
            "renewal_count": renewal_count,
            "is_active": is_active,
            "first_conversion_at": first_at,
            "latest_conversion_at": latest_at,
        }

    async def attribute_renewal(
        self,
        tenant_id: str,
        renewal_conversion_id: str,
    ) -> dict[str, Any]:
        """Attribute a renewal conversion by propagating acquisition attribution.

        Finds the original acquisition conversion for the same subscription,
        copies its active attribution credits (scaled to the renewal net_value),
        and inserts a new attribution run for the renewal.

        If no acquisition attribution exists (e.g., subscription predates system),
        attributes to unattributed (returns run with credit_total=0).
        """
        renewal = await self._conv_repo.get(tenant_id, renewal_conversion_id)
        if renewal is None:
            raise ValueError(f"Renewal conversion {renewal_conversion_id} not found")

        if renewal.get("conversion_type") not in _RENEWAL_TYPES:
            raise ValueError(
                f"Conversion {renewal_conversion_id} is not a renewal type "
                f"(got '{renewal.get('conversion_type')}')"
            )

        subscription_id = renewal.get("subscription_id")
        if not subscription_id:
            logger.warning(
                "Renewal %s has no subscription_id; cannot propagate acquisition attribution",
                renewal_conversion_id,
            )
            return await self._create_unattributed_run(tenant_id, renewal, "no_subscription_id")

        acquisition_conv = await self._find_acquisition_conversion(tenant_id, subscription_id)
        if acquisition_conv is None:
            return await self._create_unattributed_run(tenant_id, renewal, "no_acquisition_found")

        acquisition_run = await self._run_repo.get_active_run(
            tenant_id, acquisition_conv["conversion_id"]
        )
        if acquisition_run is None:
            return await self._create_unattributed_run(
                tenant_id, renewal, "no_active_acquisition_run"
            )

        acq_credits = await self._run_repo.list_credits_for_conversion(
            tenant_id, acquisition_conv["conversion_id"]
        )

        eligible_revenue = _to_decimal(
            renewal.get("net_value") or renewal.get("gross_value") or "0"
        ) or Decimal("0")

        run_id = str(uuid4())
        run = await self._run_repo.create_run({
            "attribution_run_id": run_id,
            "tenant_id": tenant_id,
            "conversion_id": renewal_conversion_id,
            "model_type": "subscription_renewal",
            "model_version": "1.0",
            "code_version": "1.0",
            "status": "running",
            "currency": renewal.get("currency", "USD"),
            "eligible_revenue": str(eligible_revenue),
            "trigger_reason": "subscription_renewal",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        credit_rows: list[dict[str, Any]] = []
        total_weight = Decimal("0")

        for src_credit in acq_credits:
            weight = _to_decimal(src_credit.get("credit_weight")) or Decimal("0")
            total_weight += weight
            credit_rows.append({
                "credit_id": str(uuid4()),
                "tenant_id": tenant_id,
                "attribution_run_id": run_id,
                "conversion_id": renewal_conversion_id,
                "touchpoint_id": src_credit.get("touchpoint_id"),
                "campaign_id": src_credit.get("campaign_id"),
                "ad_group_id": src_credit.get("ad_group_id"),
                "ad_set_id": src_credit.get("ad_set_id"),
                "creative_id": src_credit.get("creative_id"),
                "ad_id": src_credit.get("ad_id"),
                "placement_id": src_credit.get("placement_id"),
                "keyword_id": src_credit.get("keyword_id"),
                "channel": src_credit.get("channel"),
                "source": src_credit.get("source"),
                "credit_weight": str(weight),
                "attributed_conversion_count": str(weight),
                "attributed_gross_revenue": str(weight * eligible_revenue),
                "attributed_net_revenue": str(weight * eligible_revenue),
                "explanation": (
                    f"subscription_renewal: inherited from acquisition run "
                    f"{acquisition_run.get('attribution_run_id')} "
                    f"weight={float(weight):.4f}"
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        unattributed = max(Decimal("1") - total_weight, Decimal("0"))

        await self._run_repo.deactivate_prior_runs(tenant_id, renewal_conversion_id)
        await self._run_repo.insert_credits(credit_rows)

        completed = await self._run_repo.update_run(run_id, {
            "status": "complete",
            "is_active": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "credit_total": str(total_weight),
            "unattributed_credit": str(unattributed),
            "input_touchpoint_count": len(acq_credits),
            "excluded_touchpoint_count": 0,
        })

        logger.info(
            "Renewal attribution complete: run=%s renewal=%s sub=%s credits=%d weight=%s",
            run_id, renewal_conversion_id, subscription_id, len(credit_rows), total_weight,
        )
        return completed or run

    async def compute_cohort_ltv(
        self,
        tenant_id: str,
        cohort_month: str,
        *,
        conversion_type: str = "subscription_started",
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Aggregate LTV metrics for a cohort of subscriptions started in a given month.

        cohort_month: 'YYYY-MM' format.

        Returns per-cohort aggregates: count, avg_ltv, median_ltv, total_ltv,
        12-month retention rate, avg_renewals.
        """
        try:
            year, month = int(cohort_month[:4]), int(cohort_month[5:7])
        except (ValueError, IndexError):
            raise ValueError(f"cohort_month must be YYYY-MM format, got '{cohort_month}'")

        from datetime import date
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        conversions = await self._conv_repo.list_by_tenant(
            tenant_id,
            after_occurred=start_dt,
            before_occurred=end_dt,
            attribution_eligible_only=False,
            limit=limit,
        )

        acquisition_conversions = [
            c for c in conversions
            if c.get("conversion_type") == conversion_type
            and c.get("subscription_id")
        ]

        if not acquisition_conversions:
            return {
                "tenant_id": tenant_id,
                "cohort_month": cohort_month,
                "cohort_size": 0,
                "total_ltv": "0",
                "avg_ltv": "0",
            }

        ltv_values: list[Decimal] = []
        renewal_counts: list[int] = []
        total_revenue = Decimal("0")

        for conv in acquisition_conversions:
            sub_id = conv.get("subscription_id")
            if not sub_id:
                continue
            ltv_data = await self.compute_ltv(tenant_id, sub_id)
            ltv = _to_decimal(ltv_data.get("total_net_value")) or Decimal("0")
            ltv_values.append(ltv)
            renewal_counts.append(ltv_data.get("renewal_count", 0))
            total_revenue += ltv

        count = len(ltv_values)
        avg_ltv = total_revenue / count if count else Decimal("0")
        avg_renewals = sum(renewal_counts) / count if count else 0.0

        sorted_ltv = sorted(ltv_values)
        median_ltv = sorted_ltv[count // 2] if count else Decimal("0")

        return {
            "tenant_id": tenant_id,
            "cohort_month": cohort_month,
            "cohort_size": count,
            "total_ltv": str(total_revenue),
            "avg_ltv": str(avg_ltv),
            "median_ltv": str(median_ltv),
            "avg_renewals": round(avg_renewals, 2),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Private helpers ─────────────────────────────────────────────────────

    async def _load_subscription_conversions(
        self,
        tenant_id: str,
        subscription_id: str,
    ) -> list[dict[str, Any]]:
        """Load all conversions for a subscription_id, ordered by occurred_at."""
        pool = await self._conv_repo._pool()
        if pool is None:
            from services.measurement.repositories.conversion_repo import _local_store
            rows = [
                r for r in _local_store.values()
                if r.get("tenant_id") == tenant_id
                and r.get("subscription_id") == subscription_id
            ]
            rows.sort(key=lambda r: r.get("occurred_at", ""))
            return rows

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM canonical_conversions
                WHERE tenant_id = $1 AND subscription_id = $2
                ORDER BY occurred_at ASC
                """,
                tenant_id, subscription_id,
            )
            return [dict(r) for r in rows]

    async def _find_acquisition_conversion(
        self,
        tenant_id: str,
        subscription_id: str,
    ) -> Optional[dict[str, Any]]:
        """Return the earliest acquisition-type conversion for a subscription."""
        conversions = await self._load_subscription_conversions(tenant_id, subscription_id)
        for conv in conversions:
            if conv.get("conversion_type") in _ACQUISITION_TYPES:
                return conv
        # Fall back to whichever conversion came first
        return conversions[0] if conversions else None

    async def _create_unattributed_run(
        self,
        tenant_id: str,
        renewal: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        """Create a run with credit_total=0 and unattributed_credit=1 for a renewal."""
        run_id = str(uuid4())
        run = await self._run_repo.create_run({
            "attribution_run_id": run_id,
            "tenant_id": tenant_id,
            "conversion_id": renewal.get("conversion_id"),
            "model_type": "subscription_renewal",
            "model_version": "1.0",
            "code_version": "1.0",
            "status": "running",
            "currency": renewal.get("currency", "USD"),
            "eligible_revenue": str(
                _to_decimal(renewal.get("net_value") or renewal.get("gross_value") or "0")
                or Decimal("0")
            ),
            "trigger_reason": f"subscription_renewal:{reason}",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

        await self._run_repo.deactivate_prior_runs(tenant_id, renewal.get("conversion_id", ""))
        completed = await self._run_repo.update_run(run_id, {
            "status": "complete",
            "is_active": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "credit_total": "0",
            "unattributed_credit": "1",
            "input_touchpoint_count": 0,
            "excluded_touchpoint_count": 0,
            "failure_reason": reason,
        })

        logger.info(
            "Renewal unattributed: run=%s renewal=%s reason=%s",
            run_id, renewal.get("conversion_id"), reason,
        )
        return completed or run


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
