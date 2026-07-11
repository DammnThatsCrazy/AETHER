<!-- DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Metric Registry (5 metrics, contract v1)

| Metric | Version | Unit | Bounds | Allows Probability | Min Sample | Description |
|---|---|---|---|---|---|---|
| `conversion_rate` | 1 | ratio | [0.0, 1.0] | no | 30 | Share of journeys that reached a conversion. |
| `attributed_conversions` | 1 | count | [0.0, ∞] | no | 1 | Conversions credited under the active attribution model. |
| `revenue` | 1 | currency | [0.0, ∞] | no | 1 | Attributed revenue over the measurement window. |
| `touchpoints` | 1 | count | [0.0, ∞] | no | 1 | Distinct marketing touchpoints observed in the window. |
| `journey_completion_rate` | 1 | ratio | [0.0, 1.0] | no | 20 | Share of started journeys that completed. |
