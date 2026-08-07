"""The canonical computation-definition registry (hand-authored source of truth).

Seeds the substrate with:
  1. the existing Measurement Integrity Plane metrics (bridged into canonical
     definitions), and
  2. the canonical campaign / marketing economics definitions with their exact
     formulas, aggregation algebra, and null/zero policy.

A separate generator owns ``generated_registry.py`` (the JSON-parity twin) — do
not merge the two. Definitions are immutable once ``active``: registering a
changed body under an existing active key raises.
"""

from __future__ import annotations

from typing import Optional

from shared.computation.aggregation import AggregationType
from shared.computation.definition import (
    ComputationDefinition,
    ComputationKind,
    DecisionImpactClass,
    LifecycleState,
)
from shared.computation.errors import DefinitionError
from shared.computation.types import MathType

REGISTRY_VERSION: str = "1"

_GROWTH = "growth-analytics"
_MEASURE = "measurement-integrity"
_CAMPAIGN_TESTS = ["tests/computation/test_campaign_definitions.py"]


def _measurement_bridge() -> tuple[ComputationDefinition, ...]:
    """Bridge the 9 existing measurement definitions into canonical definitions."""
    from shared.measurement.registry import METRIC_REGISTRY

    defs: list[ComputationDefinition] = []
    for name, md in METRIC_REGISTRY.items():
        if md.unit == "ratio":
            output_type = MathType.RATE
            kind = ComputationKind.DETERMINISTIC_METRIC
            agg = AggregationType.RATIO_OF_SUMS
        elif md.unit == "currency":
            output_type = MathType.MONEY
            kind = ComputationKind.OBSERVED_FACT
            agg = AggregationType.SUM
        else:
            output_type = MathType.INTEGER_COUNT
            kind = ComputationKind.OBSERVED_FACT
            agg = AggregationType.SUM
        defs.append(
            ComputationDefinition(
                definition_id=f"measurement.{name}",
                definition_version=md.version,
                display_name=name.replace("_", " ").title(),
                description=md.description,
                owner=_MEASURE,
                domain="measurement",
                lifecycle_state=LifecycleState.ACTIVE,
                computation_kind=kind,
                output_type=output_type,
                unit=md.unit,
                valid_range_low=md.lower,
                valid_range_high=md.upper,
                minimum_sample_size=md.min_sample,
                aggregation_type=agg,
                decision_impact_class=DecisionImpactClass.CUSTOMER_FACING,
                tests=["tests/unit/test_measurement_results_repo.py"],
            )
        )
    return tuple(defs)


def _campaign_definitions() -> tuple[ComputationDefinition, ...]:
    """Canonical campaign / marketing economics definitions (task §14)."""

    def money(did: str, name: str, desc: str, agg: AggregationType = AggregationType.SUM):
        return ComputationDefinition(
            definition_id=did,
            definition_version="1",
            display_name=name,
            description=desc,
            owner=_GROWTH,
            domain="campaign",
            lifecycle_state=LifecycleState.ACTIVE,
            computation_kind=ComputationKind.OBSERVED_FACT,
            output_type=MathType.MONEY,
            unit="currency",
            aggregation_type=agg,
            decision_impact_class=DecisionImpactClass.FINANCIAL,
            tests=_CAMPAIGN_TESTS,
        )

    def count(did: str, name: str, desc: str, fractional: bool = False):
        return ComputationDefinition(
            definition_id=did,
            definition_version="1",
            display_name=name,
            description=desc,
            owner=_GROWTH,
            domain="campaign",
            lifecycle_state=LifecycleState.ACTIVE,
            computation_kind=(
                ComputationKind.ALLOCATED_VALUE if fractional else ComputationKind.OBSERVED_FACT
            ),
            output_type=MathType.FRACTIONAL_COUNT if fractional else MathType.INTEGER_COUNT,
            unit="count",
            aggregation_type=AggregationType.SUM,
            decision_impact_class=DecisionImpactClass.CUSTOMER_FACING,
            tests=_CAMPAIGN_TESTS,
        )

    def rate(
        did: str,
        name: str,
        desc: str,
        deps: list[str],
        *,
        unit: str = "ratio",
        min_sample: int = 1,
        bounded_proportion: bool = False,
        impact: DecisionImpactClass = DecisionImpactClass.CUSTOMER_FACING,
    ):
        return ComputationDefinition(
            definition_id=did,
            definition_version="1",
            display_name=name,
            description=desc,
            owner=_GROWTH,
            domain="campaign",
            lifecycle_state=LifecycleState.ACTIVE,
            computation_kind=ComputationKind.DETERMINISTIC_METRIC,
            output_type=MathType.RATE,
            unit=unit,
            # Bounded [0,1] proportions get a Wilson band; unbounded currency/ratio
            # rates (CPC/CPM/ROAS/CPA/AOV) do not.
            valid_range_low=0.0 if bounded_proportion else None,
            valid_range_high=1.0 if bounded_proportion else None,
            dependency_definitions=deps,
            null_policy="null_not_zero",
            zero_policy="evidence_backed",
            minimum_sample_size=min_sample,
            aggregation_type=AggregationType.RATIO_OF_SUMS,
            decision_impact_class=impact,
            tests=_CAMPAIGN_TESTS,
        )

    return (
        # Observed facts
        count("campaign.impressions", "Impressions", "Ad impressions served."),
        count("campaign.clicks", "Clicks", "Ad clicks."),
        count("campaign.engagements", "Engagements", "Engagement interactions."),
        count("campaign.provider_conversions", "Provider Conversions",
              "Conversions as reported by the ad provider."),
        count("campaign.first_party_conversions", "First-Party Conversions",
              "Conversions observed first-party by Aether."),
        count("campaign.attributed_conversions", "Attributed Conversions",
              "Fractional conversions credited under the active attribution model.",
              fractional=True),
        money("campaign.media_spend", "Media Spend", "Provider media spend in native currency."),
        money("campaign.total_cost", "Total Cost", "Media spend plus fees."),
        money("campaign.attributed_gross_revenue", "Attributed Gross Revenue",
              "Gross revenue credited to the campaign."),
        money("campaign.attributed_net_revenue", "Attributed Net Revenue",
              "Net revenue credited to the campaign."),
        money("campaign.attributed_contribution_revenue", "Attributed Contribution Revenue",
              "Contribution revenue credited to the campaign."),
        # Deterministic metrics (rates / ratio-of-sums)
        rate("campaign.cpc", "CPC", "media_spend / clicks",
             ["campaign.media_spend", "campaign.clicks"], unit="currency",
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.cpm", "CPM", "media_spend / impressions * 1000",
             ["campaign.media_spend", "campaign.impressions"], unit="currency",
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.ctr", "CTR", "clicks / impressions",
             ["campaign.clicks", "campaign.impressions"], min_sample=30,
             bounded_proportion=True),
        rate("campaign.conversion_rate", "Conversion Rate",
             "attributed_conversions / eligible_clicks",
             ["campaign.attributed_conversions", "campaign.clicks"], min_sample=30,
             bounded_proportion=True),
        rate("campaign.cpa", "CPA", "eligible_total_cost / attributed_conversions",
             ["campaign.total_cost", "campaign.attributed_conversions"], unit="currency",
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.cac", "CAC", "acquisition_cost / distinct_first_time_customers",
             ["campaign.total_cost", "campaign.first_party_conversions"], unit="currency",
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.gross_roas", "Gross ROAS", "attributed_gross_revenue / media_spend",
             ["campaign.attributed_gross_revenue", "campaign.media_spend"],
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.net_roas", "Net ROAS", "attributed_net_revenue / total_cost",
             ["campaign.attributed_net_revenue", "campaign.total_cost"],
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.contribution_roas", "Contribution ROAS",
             "attributed_contribution_revenue / total_cost",
             ["campaign.attributed_contribution_revenue", "campaign.total_cost"],
             impact=DecisionImpactClass.FINANCIAL),
        rate("campaign.aov", "AOV",
             "attributed_gross_purchase_revenue / attributed_purchase_conversions",
             ["campaign.attributed_gross_revenue", "campaign.attributed_conversions"],
             unit="currency", impact=DecisionImpactClass.FINANCIAL),
        # Allocated value
        ComputationDefinition(
            definition_id="campaign.journey_allocated_cost",
            definition_version="1",
            display_name="Journey Allocated Cost",
            description=(
                "Campaign cost allocated to a journey under an allocation policy. "
                "ESTIMATED/allocated — never observed. Conserves total campaign cost."
            ),
            owner=_GROWTH,
            domain="journey",
            lifecycle_state=LifecycleState.ACTIVE,
            computation_kind=ComputationKind.ALLOCATED_VALUE,
            output_type=MathType.MONEY,
            unit="currency",
            dependency_definitions=["campaign.total_cost"],
            allocation_policy="attribution_credit",
            aggregation_type=AggregationType.SUM,
            decision_impact_class=DecisionImpactClass.FINANCIAL,
            tests=_CAMPAIGN_TESTS + ["tests/computation/test_allocation.py"],
        ),
    )


def _governance_definitions() -> tuple[ComputationDefinition, ...]:
    """Canonical definitions for the migrated cross-domain P0/P1 computations.

    These pin the mathematical TYPE and decision-impact of each governed number
    (money is Decimal+currency; trust/fraud are heuristic scores, NOT
    probabilities; a prediction is a probability; TVL change is a balance delta,
    NOT P&L) so the inventory entries can reference a real, typed definition.
    """

    def make(
        did: str,
        name: str,
        desc: str,
        *,
        domain: str,
        owner: str,
        kind: ComputationKind,
        output: MathType,
        unit: str,
        impact: DecisionImpactClass,
        agg: AggregationType = AggregationType.NON_AGGREGATABLE,
        low: float | None = None,
        high: float | None = None,
        tests: list[str] | None = None,
    ) -> ComputationDefinition:
        return ComputationDefinition(
            definition_id=did,
            definition_version="1",
            display_name=name,
            description=desc,
            owner=owner,
            domain=domain,
            lifecycle_state=LifecycleState.ACTIVE,
            computation_kind=kind,
            output_type=output,
            unit=unit,
            valid_range_low=low,
            valid_range_high=high,
            null_policy="null_not_zero",
            zero_policy="evidence_backed",
            aggregation_type=agg,
            decision_impact_class=impact,
            tests=tests or ["tests/computation/"],
        )

    fin = DecisionImpactClass.FINANCIAL
    return (
        # ── Financial value (net-of-subtrahend, unpriced => partial) ──────────
        make("value.net_worth", "Net Worth (USD)",
             "total_portfolio_usd - liabilities_usd; unpriced liabilities => partial, never inflated.",
             domain="financial", owner="value@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.MONEY, unit="currency", impact=fin,
             tests=["tests/value/test_tvl_ltv_portfolio_account.py"]),
        make("value.net_tvl", "Net TVL (USD)",
             "gross_tvl - borrowed; unpriced debt => partial, never inflated.",
             domain="financial", owner="value@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.MONEY, unit="currency", impact=fin,
             tests=["tests/value/test_tvl_ltv_portfolio_account.py"]),
        make("value.net_ltv", "Net LTV (USD)",
             "gross_ltv - cost; unknown cost => unknown (null), never gross.",
             domain="financial", owner="value@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.MONEY, unit="currency", impact=fin,
             tests=["tests/value/test_tvl_ltv_portfolio_account.py"]),
        # ── P&L (flows vs performance; TVL change is NOT P&L) ─────────────────
        make("pnl.realized", "Realized P&L (USD)",
             "FIFO realized P&L with opening lots; missing basis => insufficient_data.",
             domain="financial", owner="pnl@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.MONEY, unit="currency", impact=fin,
             tests=["tests/computation/test_pnl_semantics.py"]),
        make("pnl.tvl_change", "TVL Change (USD)",
             "Balance-snapshot delta (deposits+withdrawals+price). NOT P&L; a flow, not performance.",
             domain="financial", owner="pnl@aether", kind=ComputationKind.OBSERVED_FACT,
             output=MathType.MONEY, unit="currency", impact=fin,
             tests=["tests/computation/test_pnl_semantics.py"]),
        # ── Billing (metered usage; truncation disclosed) ────────────────────
        make("billing.metered_usage", "Metered Usage",
             "Billable metered quantity over a period; bounded reads disclose truncation.",
             domain="billing", owner="billing@aether", kind=ComputationKind.OBSERVED_FACT,
             output=MathType.QUANTITY, unit="unit", impact=fin, agg=AggregationType.SUM,
             tests=["tests/computation/test_billing_usage.py"]),
        # ── Trust / fraud (HEURISTIC scores, not probabilities) ──────────────
        make("trust.composite", "Trust Composite (heuristic)",
             "Weighted heuristic composite in [0,1]; absent risk evidence => low prior + coverage. NOT calibrated.",
             domain="trust", owner="trust@aether", kind=ComputationKind.HEURISTIC_SCORE,
             output=MathType.HEURISTIC_SCORE, unit="score", impact=DecisionImpactClass.ACCESS_CONTROL,
             low=0.0, high=1.0, tests=["tests/computation/test_trust_evidence.py"]),
        make("fraud.risk", "Fraud Risk (heuristic)",
             "Rule/detector heuristic risk in [0,100]; evaluation failure fails closed to review. NOT a probability.",
             domain="fraud", owner="fraud@aether", kind=ComputationKind.HEURISTIC_SCORE,
             output=MathType.HEURISTIC_SCORE, unit="score", impact=DecisionImpactClass.ACCESS_CONTROL,
             low=0.0, high=100.0, tests=["tests/computation/test_fraud_failclosed.py"]),
        # ── ML prediction (probability, cache-bound to features/consent) ─────
        make("ml.prediction", "ML Prediction (probability)",
             "Model probability in [0,1]; cache key binds tenant+feature digest+consent.",
             domain="ml", owner="ml@aether", kind=ComputationKind.STATISTICAL_ESTIMATE,
             output=MathType.PROBABILITY, unit="probability", impact=DecisionImpactClass.OPERATIONAL,
             low=0.0, high=1.0, tests=["tests/computation/test_ml_cache_key.py"]),
        # ── Behavioral source freshness (dynamic SLA) ────────────────────────
        make("behavioral.source_freshness", "Source Freshness",
             "Whether a source is stale vs a dynamic freshness SLA (unknown when timestamp absent).",
             domain="behavioral", owner="behavioral@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.TRISTATE, unit="tristate", impact=DecisionImpactClass.OPERATIONAL,
             tests=["tests/computation/test_behavioral_staleness.py"]),
        # ── Cluster economics (Decimal; absent = unknown) ────────────────────
        make("cluster.economics", "Cluster Economics (USD)",
             "Decimal rollup of member revenue/spend; absent member economics are unknown, not 0.",
             domain="cluster", owner="cluster@aether", kind=ComputationKind.DETERMINISTIC_METRIC,
             output=MathType.MONEY, unit="currency", impact=DecisionImpactClass.CUSTOMER_FACING,
             agg=AggregationType.SUM, tests=["tests/computation/"]),
    )


def _build_registry() -> dict[str, ComputationDefinition]:
    registry: dict[str, ComputationDefinition] = {}
    for d in (*_measurement_bridge(), *_campaign_definitions(), *_governance_definitions()):
        registry[d.key()] = d
    return registry


COMPUTATION_REGISTRY: dict[str, ComputationDefinition] = _build_registry()


def get_definition(definition_id: str, version: str = "1") -> Optional[ComputationDefinition]:
    return COMPUTATION_REGISTRY.get(f"{definition_id}@{version}")


def list_definitions() -> list[ComputationDefinition]:
    return list(COMPUTATION_REGISTRY.values())


def list_active() -> list[ComputationDefinition]:
    return [d for d in COMPUTATION_REGISTRY.values() if d.lifecycle_state == LifecycleState.ACTIVE]


def register(definition: ComputationDefinition) -> None:
    """Register a definition, enforcing immutability of an already-active key."""
    existing = COMPUTATION_REGISTRY.get(definition.key())
    if (
        existing is not None
        and existing.lifecycle_state == LifecycleState.ACTIVE
        and existing.model_dump() != definition.model_dump()
    ):
        raise DefinitionError(
            f"active definition {definition.key()} is immutable; bump the version "
            "to change formula/scope/allocation/window semantics"
        )
    COMPUTATION_REGISTRY[definition.key()] = definition


__all__ = [
    "REGISTRY_VERSION",
    "COMPUTATION_REGISTRY",
    "get_definition",
    "list_definitions",
    "list_active",
    "register",
]
