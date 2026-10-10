"""Canonical campaign / journey economics on the Computation Substrate.

This is the authoritative computation for campaign economics — the layer the gold
materializer and every read surface should agree with. It fixes the defects the
legacy gold path carried:

  * fractional attributed conversions are PRESERVED (never ``int()``-truncated);
  * a zero/undefined denominator yields ``missing_inputs`` (null), never ``0.0``;
  * money keeps its native currency as Decimal (never a float, never hardcoded
    USD);
  * per-journey campaign cost is ALLOCATED (estimated + conserved) via the
    allocation engine, never the full campaign spend duplicated onto each journey.

Every number is returned as a :class:`CanonicalResult` carrying its definition
version, status, numerator/denominator, and quality — so all surfaces can
reference the same canonical result rather than re-deriving the formula.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from shared.computation.allocation import AllocationPolicy, AllocationResult, allocate
from shared.computation.context import ComputationContext
from shared.computation.registry import get_definition
from shared.computation.result import CanonicalResult, ResultStatus
from shared.computation.runtime import count_result, money_result, rate_result


@dataclass
class CampaignAggregates:
    """The raw, window-scoped aggregates for one campaign scope.

    Counts are integers; money values are decimal strings (or ``None`` when
    unpriced — never ``0``); ``attributed_conversions`` is a decimal string so the
    fractional attribution credit is preserved.
    """

    impressions: int = 0
    clicks: int = 0
    media_spend: Optional[str] = None
    total_cost: Optional[str] = None
    currency: str = "USD"
    attributed_conversions: Optional[str] = None  # fractional (decimal string)
    attributed_gross_revenue: Optional[str] = None
    attributed_net_revenue: Optional[str] = None
    first_party_conversions: int = 0
    extra_lineage: dict = field(default_factory=dict)


def _def(did: str):
    d = get_definition(did)
    if d is None:  # pragma: no cover - registry is seeded at import
        raise KeyError(f"canonical definition {did} is not registered")
    return d


def canonical_campaign_metrics(
    context: ComputationContext, agg: CampaignAggregates
) -> dict[str, CanonicalResult]:
    """Compute the canonical campaign metrics as CanonicalResults.

    Returns a mapping keyed by definition id. Rates use ratio-of-sums-friendly
    honest status; money preserves the native currency; attributed conversions
    stay fractional.
    """
    cur = agg.currency
    results: dict[str, CanonicalResult] = {}

    # Observed facts
    results["campaign.media_spend"] = money_result(
        _def("campaign.media_spend"), context, amount=agg.media_spend, currency=cur,
        lineage=agg.extra_lineage,
    )
    results["campaign.total_cost"] = money_result(
        _def("campaign.total_cost"), context,
        amount=agg.total_cost if agg.total_cost is not None else agg.media_spend,
        currency=cur,
    )
    results["campaign.attributed_gross_revenue"] = money_result(
        _def("campaign.attributed_gross_revenue"), context,
        amount=agg.attributed_gross_revenue, currency=cur,
    )
    results["campaign.attributed_net_revenue"] = money_result(
        _def("campaign.attributed_net_revenue"), context,
        amount=agg.attributed_net_revenue, currency=cur,
    )
    # Fractional attributed conversions — preserved, never int()-truncated.
    results["campaign.attributed_conversions"] = count_result(
        _def("campaign.attributed_conversions"), context,
        amount=agg.attributed_conversions, fractional=True,
    )

    # Deterministic metrics (rates). Undefined denominator -> missing_inputs.
    results["campaign.ctr"] = rate_result(
        _def("campaign.ctr"), context, numerator=agg.clicks, denominator=agg.impressions,
    )
    results["campaign.cpc"] = rate_result(
        _def("campaign.cpc"), context, numerator=agg.media_spend, denominator=agg.clicks,
    )
    # CPM = media_spend / impressions * 1000 — expressed as spend per 1000
    # impressions. The denominator is computed as an EXACT Decimal (impressions /
    # 1000): a Python float here would be rejected by the money-grade to_decimal
    # and render CPM structurally missing_inputs for every impression count.
    results["campaign.cpm"] = rate_result(
        _def("campaign.cpm"), context,
        numerator=agg.media_spend,
        denominator=(Decimal(agg.impressions) / 1000) if agg.impressions else 0,
    )
    results["campaign.conversion_rate"] = rate_result(
        _def("campaign.conversion_rate"), context,
        numerator=agg.attributed_conversions, denominator=agg.clicks,
    )
    results["campaign.cpa"] = rate_result(
        _def("campaign.cpa"), context,
        numerator=agg.total_cost if agg.total_cost is not None else agg.media_spend,
        denominator=agg.attributed_conversions,
    )
    results["campaign.gross_roas"] = rate_result(
        _def("campaign.gross_roas"), context,
        numerator=agg.attributed_gross_revenue, denominator=agg.media_spend,
    )
    results["campaign.net_roas"] = rate_result(
        _def("campaign.net_roas"), context,
        numerator=agg.attributed_net_revenue,
        denominator=agg.total_cost if agg.total_cost is not None else agg.media_spend,
    )
    results["campaign.aov"] = rate_result(
        _def("campaign.aov"), context,
        numerator=agg.attributed_gross_revenue, denominator=agg.attributed_conversions,
    )
    return results


def canonical_journey_allocated_cost(
    context: ComputationContext,
    *,
    campaign_cost: str,
    currency: str,
    journey_weights: dict[str, object],
    policy: AllocationPolicy = AllocationPolicy.ATTRIBUTION_CREDIT,
) -> tuple[AllocationResult, dict[str, CanonicalResult]]:
    """Allocate a campaign's cost across journeys, conserving the total.

    This replaces the legacy behavior of adding the FULL campaign spend to every
    journey. Each journey's cost is an ALLOCATED (estimated) money result; the
    sum of allocations + residual equals the campaign cost exactly.
    """
    allocation = allocate(
        source_amount=campaign_cost,
        currency=currency,
        weights=journey_weights,
        policy=policy,
    )
    definition = _def("campaign.journey_allocated_cost")
    per_journey: dict[str, CanonicalResult] = {}
    for target in allocation.targets:
        jctx = context.model_copy(update={"subject_type": "journey", "subject_id": target.target_id})
        res = money_result(
            definition, jctx,
            amount=target.allocated_amount, currency=currency,
            status=ResultStatus.ESTIMATED,  # allocated, not observed
            lineage={
                "allocation_policy": allocation.policy.value,
                "allocation_policy_version": allocation.policy_version,
                "weight": target.weight,
                "source_campaign_cost": allocation.source_amount,
                "residual": allocation.residual,
            },
        )
        res.allocation = {
            "policy": allocation.policy.value,
            "basis": allocation.basis,
            "residual": allocation.residual,
        }
        per_journey[target.target_id] = res
    return allocation, per_journey


__all__ = [
    "CampaignAggregates",
    "canonical_campaign_metrics",
    "canonical_journey_allocated_cost",
]
