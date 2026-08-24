<!-- DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json -->
<!-- Run: python scripts/generate_contracts.py -->

# Aether Metric Registry (20 metrics, contract v1)

| Metric | Version | Unit | Bounds | Allows Probability | Min Sample | Description |
|---|---|---|---|---|---|---|
| `attributed_conversions` | 1 | count | [0, ∞] | no | 1 | Conversions credited under the active attribution model. |
| `campaign_cac` | 1 | usd | [0, ∞] | no | 1 | Customer acquisition cost for a campaign. |
| `campaign_ltv` | 1 | usd | [0, ∞] | no | 1 | Customer lifetime value attributed to a campaign. |
| `campaign_roas` | 1 | ratio | [0, ∞] | no | 1 | Return on ad spend for a campaign. |
| `campaign_spend` | 1 | usd | [0, ∞] | no | 1 | Media and allocated cost spent on a campaign. |
| `conversion_rate` | 1 | ratio | [0, 1] | no | 30 | Share of journeys that reached a conversion. |
| `costs` | 1 | usd | [-∞, ∞] | no | 1 | Total costs incurred over the measurement window. |
| `email_click_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a qualified click. |
| `email_open_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a qualified open. |
| `email_reply_rate` | 1 | ratio | [0, 1] | no | 30 | Share of delivered campaign messages with a human reply. |
| `exposure` | 1 | usd | [-∞, ∞] | no | 1 | Observed economic exposure over the measurement window. |
| `gross_value` | 1 | usd | [-∞, ∞] | no | 1 | Gross economic value observed over the window. |
| `journey_completion_rate` | 1 | ratio | [0, 1] | no | 20 | Share of started journeys that completed. |
| `ltv` | 1 | usd | [-∞, ∞] | no | 1 | Customer lifetime value over the measurement window. |
| `machine_event_rate` | 1 | ratio | [0, 1] | no | 30 | Share of campaign communication events classified as machine generated. |
| `margin` | 1 | ratio | [-∞, ∞] | no | 1 | Profit margin ratio over the measurement window. |
| `net_value` | 1 | usd | [-∞, ∞] | no | 1 | Net economic value observed over the window. |
| `refunds` | 1 | usd | [-∞, ∞] | no | 1 | Refunds issued over the measurement window. |
| `revenue` | 1 | currency | [0, ∞] | no | 1 | Attributed revenue over the measurement window. |
| `touchpoints` | 1 | count | [0, ∞] | no | 1 | Distinct marketing touchpoints observed in the window. |
