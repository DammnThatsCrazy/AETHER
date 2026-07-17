<!-- DO NOT EDIT — generated from packages/shared/contracts/comparison-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Comparison Registry

Contract version: `1.0.0`

## Comparison modes

`entity_vs_entity`, `entity_vs_history`, `entity_vs_cohort`, `entity_vs_expected`, `cohort_vs_cohort`, `scenario_vs_current`

## Baseline types

`entity`, `historical`, `rolling_history`, `cohort`, `policy`, `predicted`, `manual`, `scenario`

## Alignment outcomes

`aligned`, `aligned_after_conversion`, `partially_aligned`, `not_comparable`, `missing_unit`, `missing_price`, `stale_price`, `grain_mismatch`, `semantic_mismatch`, `insufficient_provenance`

## Run states

`queued`, `resolving`, `collecting`, `aligning`, `computing`, `scoring`, `completed`, `completed_degraded`, `suppressed`, `failed`, `cancelled`, `expired`

## Severities

`info`, `low`, `medium`, `high`, `critical`

## Dispositions

`informational`, `monitor`, `investigate`, `decide`, `act`, `suppressed`, `insufficient_evidence`

## Fact linkage states

`linked`, `deterministically_linked`, `probabilistically_linked`, `pending`, `conflicted`, `suppressed`, `intentionally_unlinked`, `orphaned`, `revoked`, `superseded`

## Causal claim levels

`observed`, `correlated`, `temporally_associated`, `attributed`, `inferred`, `counterfactual_estimate`, `causally_supported`

## Comparison dimensions

`identity`, `relationships`, `devices`, `sessions`, `behavior`, `journeys`, `campaigns`, `attribution`, `wallets`, `economic_activity`, `agent_behavior`, `fraud_risk`, `trust`, `consent`, `governance`, `outcomes`, `data_quality`, `reconciliation`, `geography`, `temporal_activity`

## Materiality components

`economic_impact`, `risk_impact`, `policy_impact`, `relationship_rarity`, `historical_deviation`, `cohort_deviation`, `propagation_radius`, `confidence`, `freshness`, `persistence`, `urgency`, `strategic_entity_weight`, `reversibility`, `data_quality`
