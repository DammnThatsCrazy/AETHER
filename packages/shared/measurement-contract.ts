      // =============================================================================
      // Aether SDK — Shared Metric Registry Contract (v1)
      // DO NOT EDIT — generated from packages/shared/contracts/metric-registry.json
      // Run: python scripts/generate_contracts.py
      // =============================================================================

      /** Contract version of the canonical metric registry. */
      export const metricRegistryVersion = '1';

      /** Canonical metric names the measurement plane knows how to report. */
      export type MetricName =
        | 'conversion_rate'
| 'attributed_conversions'
| 'revenue'
| 'touchpoints'
| 'journey_completion_rate'
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
  name: 'conversion_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of journeys that reached a conversion.',
  lower: 0.0,
  upper: 1.0,
  allowsProbability: false,
  minSample: 30,
},
{
  name: 'attributed_conversions',
  version: '1',
  unit: 'count',
  description: 'Conversions credited under the active attribution model.',
  lower: 0.0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'revenue',
  version: '1',
  unit: 'currency',
  description: 'Attributed revenue over the measurement window.',
  lower: 0.0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'touchpoints',
  version: '1',
  unit: 'count',
  description: 'Distinct marketing touchpoints observed in the window.',
  lower: 0.0,
  upper: null,
  allowsProbability: false,
  minSample: 1,
},
{
  name: 'journey_completion_rate',
  version: '1',
  unit: 'ratio',
  description: 'Share of started journeys that completed.',
  lower: 0.0,
  upper: 1.0,
  allowsProbability: false,
  minSample: 20,
},
      ] as const;
