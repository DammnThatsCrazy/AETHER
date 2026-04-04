import { useState, useEffect } from 'react';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockMissionData } from '@shiki/fixtures/mission';
import { api } from '@shiki/lib/api/endpoints';
import type { Severity } from '@shiki/types';

interface DashboardSummaryResponse {
  sessions_last_24h?: number;
  events_last_24h?: number;
  unique_users_last_24h?: number;
  top_events?: { name: string; count: number }[];
  [key: string]: unknown;
}

interface InsightsResponse {
  command_brief?: string;
  recommendations?: { id: string; title: string; description: string; action_class: number; confidence: number; reversible: boolean; controller: string; rationale: string; entity_id?: string }[];
  key_changes_1h?: { id: string; description: string; severity: string; timestamp: string; controller: string; entity_id?: string; entity_type?: string }[];
  key_changes_24h?: { id: string; description: string; severity: string; timestamp: string; controller: string; entity_id?: string; entity_type?: string }[];
  key_changes_7d?: { id: string; description: string; severity: string; timestamp: string; controller: string; entity_id?: string; entity_type?: string }[];
  pending_approvals?: number;
  customers_needing_help?: unknown[];
  agents_needing_help?: unknown[];
  recent_interventions?: unknown[];
  [key: string]: unknown;
}

type BriefData = ReturnType<typeof getMockMissionData>;

function mapToBriefData(summary: DashboardSummaryResponse, insights: InsightsResponse): BriefData {
  const now = new Date().toISOString();

  const mapKeyChanges = (
    raw?: { id: string; description: string; severity: string; timestamp: string; controller: string; entity_id?: string; entity_type?: string }[],
  ) =>
    (raw ?? []).map(kc => ({
      id: kc.id,
      description: kc.description,
      severity: (kc.severity as Severity) ?? 'info',
      timestamp: kc.timestamp,
      controller: kc.controller,
      entityId: kc.entity_id,
      entityType: kc.entity_type,
    }));

  return {
    throughput: {
      eventsPerSecond: (summary.events_last_24h ?? 0) / 86400,
      eventsPerMinute: (summary.events_last_24h ?? 0) / 1440,
      totalLast1h: Math.round((summary.events_last_24h ?? 0) / 24),
      totalLast24h: summary.events_last_24h ?? 0,
      trend: 'stable' as const,
    },
    keyChanges1h: mapKeyChanges(insights.key_changes_1h),
    keyChanges24h: mapKeyChanges(insights.key_changes_24h),
    keyChanges7d: mapKeyChanges(insights.key_changes_7d),
    recommendedActions: (insights.recommendations ?? []).map(r => ({
      id: r.id,
      title: r.title,
      description: r.description,
      actionClass: r.action_class,
      confidence: r.confidence,
      reversible: r.reversible,
      controller: r.controller,
      rationale: r.rationale,
      entityId: r.entity_id,
    })),
    globalHealth: { status: 'healthy' as const, lastChecked: now },
    customerHealth: {
      status: { status: 'healthy' as const, lastChecked: now },
      total: summary.unique_users_last_24h ?? 0,
      healthy: summary.unique_users_last_24h ?? 0,
      degraded: 0,
      unhealthy: 0,
    },
    agentHealth: {
      status: { status: 'healthy' as const, lastChecked: now },
      total: 0,
      active: 0,
      stuck: 0,
      idle: 0,
    },
    graphHealth: {
      status: { status: 'healthy' as const, lastChecked: now },
      nodeCount: 0,
      edgeCount: 0,
      lastMutation: now,
    },
    commandBrief: insights.command_brief ?? '',
    pendingApprovals: insights.pending_approvals ?? 0,
    activeAlerts: {
      total: 0,
      bySeverity: { P0: 0, P1: 0, P2: 0, P3: 0, info: 0 },
    },
    customersNeedingHelp: (insights.customers_needing_help ?? []) as BriefData['customersNeedingHelp'],
    agentsNeedingHelp: (insights.agents_needing_help ?? []) as BriefData['agentsNeedingHelp'],
    recentInterventions: (insights.recent_interventions ?? []) as BriefData['recentInterventions'],
  } as BriefData;
}

export function useBriefData() {
  const [data, setData] = useState<BriefData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setData(getMockMissionData());
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    Promise.all([
      api.analytics.dashboardSummary(),
      api.automation.insights(),
    ])
      .then(([summary, insights]) => {
        const mapped = mapToBriefData(
          summary as DashboardSummaryResponse,
          insights as InsightsResponse,
        );
        setData(mapped);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load brief data');
        setIsLoading(false);
      });
  }, []);

  return { data, isLoading, error };
}
