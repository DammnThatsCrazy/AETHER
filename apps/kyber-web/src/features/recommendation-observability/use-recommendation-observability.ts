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

  const queries = [strategicOverview, tenantValueHealth, familyPerformance, playbookPerformance, modelConfidenceDrift, verticalSolutionSignals, revenueOpportunities];
  return {
    enabled,
    strategicOverview,
    tenantValueHealth,
    familyPerformance,
    playbookPerformance,
    modelConfidenceDrift,
    verticalSolutionSignals,
    revenueOpportunities,
    isLoading: queries.some((query) => query.isLoading),
    error: queries.find((query) => query.error)?.error,
  };
}
