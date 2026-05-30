import { useState, useEffect } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { getMockMissionData } from '@kyber/fixtures/mission';
import { api } from '@kyber/lib/api/endpoints';
import type { ThroughputMetrics, KeyChange, RecommendedAction, HealthStatus, Severity, NeedsHelpCard, Intervention } from '@kyber/types';

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

interface DashboardSummaryResponse {
  sessions_last_24h?: number;
  events_last_24h?: number;
  unique_users_last_24h?: number;
  top_events?: { name: string; count: number }[];
  [key: string]: unknown;
}

interface HealthResponse {
  status: string;
  uptime?: number;
  services?: Record<string, { status: string; latency_ms?: number; error?: string | null }>;
  [key: string]: unknown;
}

interface AlertsResponse {
  alerts: { id?: string; name: string; severity?: string; active?: boolean; [key: string]: unknown }[];
  count: number;
}

interface AgentStatusResponse {
  active_workers?: number;
  queued_tasks?: number;
  completed_tasks?: number;
  failed_tasks?: number;
  workers?: { worker_type: string; status: string; current_task?: string | null }[];
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

function mapToMissionData(
  summary: DashboardSummaryResponse,
  health: HealthResponse,
  alerts: AlertsResponse,
  agentStatus: AgentStatusResponse,
  insights: InsightsResponse,
): MissionData {
  const now = new Date().toISOString();

  const mapKeyChanges = (
    raw?: { id: string; description: string; severity: string; timestamp: string; controller: string; entity_id?: string; entity_type?: string }[],
  ): KeyChange[] =>
    (raw ?? []).map(kc => ({
      id: kc.id,
      description: kc.description,
      severity: (kc.severity as Severity) ?? 'info',
      timestamp: kc.timestamp,
      controller: kc.controller,
      entityId: kc.entity_id,
      entityType: kc.entity_type,
    }));

  const overallStatus = health.status === 'ok' || health.status === 'healthy' ? 'healthy' : health.status === 'degraded' ? 'degraded' : 'unhealthy';
  const globalHealth: HealthStatus = { status: overallStatus as HealthStatus['status'], lastChecked: now };

  const workers = agentStatus.workers ?? [];
  const activeWorkers = workers.filter(w => w.status === 'active' || w.status === 'running').length;
  const stuckWorkers = workers.filter(w => w.status === 'stuck').length;
  const idleWorkers = workers.filter(w => w.status === 'idle').length;

  const agentHealthStatus: HealthStatus['status'] = stuckWorkers > 0 ? 'degraded' : activeWorkers > 0 ? 'healthy' : 'unknown';

  const severityBuckets: Record<Severity, number> = { P0: 0, P1: 0, P2: 0, P3: 0, info: 0 };
  for (const alert of alerts.alerts) {
    const sev = (alert.severity as Severity) ?? 'info';
    if (sev in severityBuckets) {
      severityBuckets[sev]++;
    }
  }

  return {
    throughput: {
      eventsPerSecond: (summary.events_last_24h ?? 0) / 86400,
      eventsPerMinute: (summary.events_last_24h ?? 0) / 1440,
      totalLast1h: Math.round((summary.events_last_24h ?? 0) / 24),
      totalLast24h: summary.events_last_24h ?? 0,
      trend: 'stable',
    },
    keyChanges1h: mapKeyChanges(insights.key_changes_1h),
    keyChanges24h: mapKeyChanges(insights.key_changes_24h),
    keyChanges7d: mapKeyChanges(insights.key_changes_7d),
    recommendedActions: (insights.recommendations ?? []).map(r => ({
      id: r.id,
      title: r.title,
      description: r.description,
      actionClass: r.action_class as RecommendedAction['actionClass'],
      confidence: r.confidence,
      reversible: r.reversible,
      controller: r.controller,
      rationale: r.rationale,
      entityId: r.entity_id,
    })),
    globalHealth,
    customerHealth: {
      status: globalHealth,
      total: summary.unique_users_last_24h ?? 0,
      healthy: summary.unique_users_last_24h ?? 0,
      degraded: 0,
      unhealthy: 0,
    },
    agentHealth: {
      status: { status: agentHealthStatus, lastChecked: now },
      total: workers.length,
      active: activeWorkers,
      stuck: stuckWorkers,
      idle: idleWorkers,
    },
    graphHealth: {
      status: globalHealth,
      nodeCount: 0,
      edgeCount: 0,
      lastMutation: now,
    },
    commandBrief: insights.command_brief ?? '',
    pendingApprovals: insights.pending_approvals ?? 0,
    activeAlerts: {
      total: alerts.count,
      bySeverity: severityBuckets,
    },
    customersNeedingHelp: (insights.customers_needing_help ?? []) as NeedsHelpCard[],
    agentsNeedingHelp: (insights.agents_needing_help ?? []) as NeedsHelpCard[],
    recentInterventions: (insights.recent_interventions ?? []) as Intervention[],
  };
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
      api.analytics.dashboardSummary(),
      api.diagnostics.health(),
      api.intelligence.alerts(),
      api.agent.status(),
      api.automation.insights(),
    ])
      .then(([summary, health, alerts, agentStatus, insights]) => {
        const mapped = mapToMissionData(
          summary as DashboardSummaryResponse,
          health as HealthResponse,
          alerts as AlertsResponse,
          agentStatus as AgentStatusResponse,
          insights as InsightsResponse,
        );
        setData(mapped);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load mission data');
        setIsLoading(false);
      });
  }, []);

  return { data, isLoading, error };
}
