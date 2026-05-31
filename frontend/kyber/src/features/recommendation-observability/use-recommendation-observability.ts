import { useMemo } from 'react';

export interface RecommendationObservabilityMetric {
  label: string;
  value: string;
  status: 'healthy' | 'warning' | 'critical';
}

export function useRecommendationObservability() {
  return useMemo(() => ({
    enabled: import.meta.env.VITE_KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED !== 'false',
    metrics: [
      { label: 'Recommendation volume', value: 'Aggregate by tenant', status: 'healthy' },
      { label: 'Approval / rejection rate', value: 'Decision records', status: 'healthy' },
      { label: 'Outcome capture rate', value: 'Outcome feedback loop', status: 'warning' },
      { label: 'Recommendation accuracy', value: 'Confidence deltas', status: 'healthy' },
      { label: 'Model confidence drift', value: 'Scoring telemetry', status: 'warning' },
      { label: 'Playbook performance', value: 'Run health', status: 'healthy' },
      { label: 'Failed or stale loops', value: 'Freshness gates', status: 'critical' },
      { label: 'Graph/action/outcome feedback health', value: 'OODA graph edges', status: 'healthy' },
    ] satisfies RecommendationObservabilityMetric[],
  }), []);
}
