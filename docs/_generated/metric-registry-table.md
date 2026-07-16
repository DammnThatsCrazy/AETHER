<!-- DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Metric Registry (9 metrics, contract v1)

| Metric | Version | Unit | Bounds | Allows Probability | Min Sample | Description |
|---|---|---|---|---|---|---|
| `conversion_rate` | 1 | ratio | [0, 1] | no | 30 | Share of journeys that reached a conversion. |
| `attributed_conversions` | 1 | count | [0, ∞] | no | 1 | Conversions credited under the active attribution model. |
| `revenue` | 1 | currency | [0, ∞] | no | 1 | Attributed revenue over the measurement window. |
| `touchpoints` | 1 | count | [0, ∞] | no | 1 | Distinct marketing touchpoints observed in the window. |
| `journey_completion_rate` | 1 | ratio | [0, 1] | no | 20 | Share of started journeys that completed. |
| `email_open_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a qualified open. |
| `email_click_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a qualified click. |
| `email_reply_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a human reply. |
| `machine_event_rate` | 1 | ratio | [0, 1] | no | 30 | Share of campaign communication events classified as machine generated. |
