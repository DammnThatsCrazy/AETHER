      // =============================================================================
      // Aether SDK — Shared Metric Registry Contract (v1)
      // DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json
      // Run: python scripts/generate_contracts.py
      // =============================================================================

      /** Contract version of the canonical metric registry. */
      export const metricRegistryVersion = '1';

      /** Canonical metric names the measurement plane knows how to report. */
      export type MetricName =
        | 'attributed_conversions'
| 'campaign_cac'
| 'campaign_ltv'
| 'campaign_roas'
| 'campaign_spend'
| 'conversion_rate'
| 'costs'
| 'email_click_rate'
| 'email_open_rate'
| 'email_reply_rate'
| 'exposure'
| 'gross_value'
| 'journey_completion_rate'
| 'ltv'
| 'machine_event_rate'
| 'margin'
| 'net_value'
| 'refunds'
| 'revenue'
| 'touchpoints'
        ;

      /** Definition of a single measurable metric. */
      export interface MetricDefinition {
        name: MetricName;
        version: string;
        unit: string;
        description: string;
        lower: number | null;
        upper: number | null;
        allowsProbability: boolean;
        minSample: number;
      }

      /** Every registered metric definition, keyed positionally by MetricName. */
      export const metricDefinitions: readonly MetricDefinition[] = [
        {
  name: 'attributed_conversions',
  version: '1',
  unit: 'count',
  description: 'Conversions credited under the active attribution model.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'campaign_cac',
  version: '1',
  unit: 'usd',
  description: 'Customer acquisition cost for a campaign.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'campaign_ltv',
  version: '1',
  unit: 'usd',
  description: 'Customer lifetime value attributed to a campaign.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'campaign_roas',
  version: '1',
  unit: 'ratio',
  description: 'Return on ad spend for a campaign.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'campaign_spend',
  version: '1',
  unit: 'usd',
  description: 'Media and allocated cost spent on a campaign.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'conversion_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of journeys that reached a conversion.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'costs',
  version: '1',
  unit: 'usd',
  description: 'Total costs incurred over the measurement window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'email_click_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of delivered campaign messages with a qualified click.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'email_open_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of delivered campaign messages with a qualified open.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'email_reply_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of delivered campaign messages with a human reply.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'exposure',
  version: '1',
  unit: 'usd',
  description: 'Observed economic exposure over the measurement window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'gross_value',
  version: '1',
  unit: 'usd',
  description: 'Gross economic value observed over the window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'journey_completion_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of started journeys that completed.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 20,
},
{
  name: 'ltv',
  version: '1',
  unit: 'usd',
  description: 'Customer lifetime value over the measurement window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'machine_event_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of campaign communication events classified as machine generated.',
  lower: 0,
  upper: 1,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'margin',
  version: '1',
  unit: 'ratio',
  description: 'Profit margin ratio over the measurement window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'net_value',
  version: '1',
  unit: 'usd',
  description: 'Net economic value observed over the window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'refunds',
  version: '1',
  unit: 'usd',
  description: 'Refunds issued over the measurement window.',
  lower: null,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'revenue',
  version: '1',
  unit: 'currency',
  description: 'Attributed revenue over the measurement window.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'touchpoints',
  version: '1',
  unit: 'count',
  description: 'Distinct marketing touchpoints observed in the window.',
  lower: 0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
      ] as const;
