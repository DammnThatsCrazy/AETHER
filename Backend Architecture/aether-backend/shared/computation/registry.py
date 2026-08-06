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


def _build_registry() -> dict[str, ComputationDefinition]:
    registry: dict[str, ComputationDefinition] = {}
    for d in (*_measurement_bridge(), *_campaign_definitions()):
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
