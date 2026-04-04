import { useState, useEffect } from 'react';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockMissionData } from '@shiki/fixtures/mission';
import type { ThroughputMetrics, KeyChange, RecommendedAction, HealthStatus, Severity, NeedsHelpCard, Intervention } from '@shiki/types';

export interface MissionData {
  readonly throughput: ThroughputMetrics;
  readonly keyChanges1h: readonly KeyChange[];
  readonly keyChanges24h: readonly KeyChange[];
  readonly keyChanges7d: readonly KeyChange[];
  readonly recommendedActions: readonly RecommendedAction[];
  readonly globalHealth: HealthStatus;
  readonly customerHealth: { readonly status: HealthStatus; readonly total: number; readonly healthy: number; readonly degraded: number; readonly unhealthy: number };
  readonly agentHealth: { readonly status: HealthStatus; readonly total: number; readonly active: number; readonly stuck: number; readonly idle: number };
  readonly graphHealth: { readonly status: HealthStatus; readonly nodeCount: number; readonly edgeCount: number; readonly lastMutation: string };
  readonly commandBrief: string;
  readonly pendingApprovals: number;
  readonly activeAlerts: { readonly total: number; readonly bySeverity: Record<Severity, number> };
  readonly customersNeedingHelp: readonly NeedsHelpCard[];
  readonly agentsNeedingHelp: readonly NeedsHelpCard[];
  readonly recentInterventions: readonly Intervention[];
}

export function useMissionData() {
  const [data, setData] = useState<MissionData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setData(getMockMissionData());
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    Promise.all([
      fetch('/api/v1/analytics/dashboard/summary').then(r => r.json()),
    ])
      .then(() => {
        // Map responses — for now use mock data shape
        setData(getMockMissionData());
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load mission data');
        setIsLoading(false);
      });
  }, []);

  return { data, isLoading, error };
}
