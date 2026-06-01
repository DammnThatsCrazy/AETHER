import { useMemo } from 'react';
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

export type KyberWindow = '7d' | '30d' | '90d' | 'lifetime';

const STALE = 60_000;

export function useRecommendationObservability(window: KyberWindow = '30d') {
  const enabled = import.meta.env.VITE_KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED === 'true';
  const strategicOverview = useQuery({
    key: `kyber:strategic-overview:${window}`,
    fetcher: () => api.admin.kyber.strategicOverview(window),
    staleTime: STALE,
    enabled,
  });
  const tenantValueHealth = useQuery({
    key: `kyber:tenant-value-health:${window}`,
    fetcher: () => api.admin.kyber.tenantValueHealth(window),
    staleTime: STALE,
    enabled,
  });
  const familyPerformance = useQuery({
    key: `kyber:family-performance:${window}`,
    fetcher: () => api.admin.kyber.recommendationFamilyPerformance(window),
    staleTime: STALE,
    enabled,
  });
  const playbookPerformance = useQuery({
    key: `kyber:playbook-performance:${window}`,
    fetcher: () => api.admin.kyber.playbookPerformance(window),
    staleTime: STALE,
    enabled,
  });
  const modelConfidenceDrift = useQuery({
    key: `kyber:model-confidence-drift:${window}`,
    fetcher: () => api.admin.kyber.modelConfidenceDrift(window),
    staleTime: STALE,
    enabled,
  });
  const verticalSolutionSignals = useQuery({
    key: `kyber:vertical-solution-signals:${window}`,
    fetcher: () => api.admin.kyber.verticalSolutionSignals(window),
    staleTime: STALE,
    enabled,
  });
  const revenueOpportunities = useQuery({
    key: `kyber:revenue-opportunities:${window}`,
    fetcher: () => api.admin.kyber.revenueOpportunities(window),
    staleTime: STALE,
    enabled,
  });

const asRecord = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' ? value as Record<string, unknown> : {});
const asNumber = (value: unknown): number => (typeof value === 'number' ? value : Number(value ?? 0));

export function useRecommendationObservability() {
  const enabled = import.meta.env.VITE_KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED === 'true';
  const recommendationHealth = useQuery({
    key: 'kyber:recommendation-health',
    fetcher: () => api.admin.kyber.recommendationHealth(),
    staleTime: 120_000,
    enabled,
  });
  const tenantValueHealth = useQuery({
    key: 'kyber:tenant-value-health',
    fetcher: () => api.admin.kyber.tenantValueHealth(),
    staleTime: 120_000,
    enabled,
  });
  const outcomeCaptureHealth = useQuery({
    key: 'kyber:outcome-capture-health',
    fetcher: () => api.admin.kyber.outcomeCaptureHealth(),
    staleTime: 120_000,
    enabled,
  });
  const playbookPerformance = useQuery({
    key: 'kyber:playbook-performance',
    fetcher: () => api.admin.kyber.playbookPerformance(),
    staleTime: 120_000,
    enabled,
  });
  const confidenceDrift = useQuery({
    key: 'kyber:model-confidence-drift',
    fetcher: () => api.admin.kyber.modelConfidenceDrift(),
    staleTime: 120_000,
    enabled,
  });

  return useMemo(() => {
    const aggregate = asRecord(asRecord(recommendationHealth.data).aggregate);
    const tenantItems = Array.isArray(asRecord(tenantValueHealth.data).items) ? asRecord(tenantValueHealth.data).items as Array<Record<string, unknown>> : [];
    const captureItems = Array.isArray(asRecord(outcomeCaptureHealth.data).items) ? asRecord(outcomeCaptureHealth.data).items as Array<Record<string, unknown>> : [];
    const playbookItems = Array.isArray(asRecord(playbookPerformance.data).items) ? asRecord(playbookPerformance.data).items as Array<Record<string, unknown>> : [];
    const drift = asNumber(asRecord(confidenceDrift.data).total_delta);
    const recommendations = asNumber(aggregate.recommendations_generated);
    const decisions = asNumber(aggregate.decisions_recorded);
    const actions = asNumber(aggregate.actions_logged);
    const outcomes = asNumber(aggregate.outcomes_observed);
    const captureRate = asNumber(aggregate.outcome_capture_rate);
    const staleLoops = asNumber(aggregate.stale_loops);
    const failedLoops = asNumber(aggregate.failed_loops);
    const valueCreated = asNumber(aggregate.observed_value);
    const atRisk = tenantItems.filter(item => item.at_risk).length;
    const expansionReady = tenantItems.filter(item => item.expansion_ready).length;

    const metrics = [
      { label: 'Recommendation volume', value: `${recommendations} generated across ${tenantItems.length || captureItems.length} tenants`, status: recommendations > 0 ? 'healthy' : 'warning' },
      { label: 'Adoption rate', value: `${decisions} decisions / ${recommendations} recommendations`, status: recommendations === 0 || decisions / Math.max(recommendations, 1) >= 0.25 ? 'healthy' : 'warning' },
      { label: 'Action logging rate', value: `${actions} actions logged`, status: decisions === 0 || actions / Math.max(decisions, 1) >= 0.5 ? 'healthy' : 'warning' },
      { label: 'Outcome capture rate', value: `${Math.round(captureRate * 100)}% (${outcomes} outcomes)`, status: captureRate >= 0.5 ? 'healthy' : captureRate >= 0.25 ? 'warning' : 'critical' },
      { label: 'Tenant value created', value: `$${valueCreated.toLocaleString()} observed`, status: valueCreated > 0 ? 'healthy' : 'warning' },
      { label: 'Model confidence drift', value: `${drift >= 0 ? '+' : ''}${drift.toFixed(2)} total delta`, status: Math.abs(drift) <= 0.5 ? 'healthy' : 'warning' },
      { label: 'Playbook performance', value: `${playbookItems.length} playbook runs aggregated`, status: playbookItems.some(item => item.stale) ? 'warning' : 'healthy' },
      { label: 'Failed or stale loops', value: `${failedLoops} failed / ${staleLoops} stale`, status: failedLoops > 0 ? 'critical' : staleLoops > 0 ? 'warning' : 'healthy' },
      { label: 'Churn risk / expansion', value: `${atRisk} tenants at risk, ${expansionReady} expansion-ready`, status: atRisk > expansionReady ? 'warning' : 'healthy' },
    ] satisfies RecommendationObservabilityMetric[];

    return {
      enabled,
      isLoading: recommendationHealth.isLoading || tenantValueHealth.isLoading || outcomeCaptureHealth.isLoading || playbookPerformance.isLoading || confidenceDrift.isLoading,
      error: recommendationHealth.error ?? tenantValueHealth.error ?? outcomeCaptureHealth.error ?? playbookPerformance.error ?? confidenceDrift.error,
      metrics,
    };
  }, [enabled, recommendationHealth.data, recommendationHealth.error, recommendationHealth.isLoading, tenantValueHealth.data, tenantValueHealth.error, tenantValueHealth.isLoading, outcomeCaptureHealth.data, outcomeCaptureHealth.error, outcomeCaptureHealth.isLoading, playbookPerformance.data, playbookPerformance.error, playbookPerformance.isLoading, confidenceDrift.data, confidenceDrift.error, confidenceDrift.isLoading]);
}
