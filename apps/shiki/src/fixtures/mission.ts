import type {
  ThroughputMetrics,
  KeyChange,
  RecommendedAction,
  HealthStatus,
  Severity,
} from '@shiki/types';
import type { NeedsHelpCard, Intervention } from '@shiki/types';

const now = new Date();
const ago = (minutes: number) => new Date(now.getTime() - minutes * 60_000).toISOString();

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

export function getMockMissionData(): MissionData {
  return {
    throughput: {
      eventsPerSecond: 342,
      eventsPerMinute: 20_520,
      totalLast1h: 1_231_200,
      totalLast24h: 28_492_800,
      trend: 'up',
    },
    globalHealth: {
      status: 'degraded',
      message: 'Redis cache experiencing elevated latency; notification service unreachable',
      lastChecked: ago(1),
    },
    customerHealth: {
      status: { status: 'degraded', message: '2 customers need attention', lastChecked: ago(1) },
      total: 148,
      healthy: 141,
      degraded: 5,
      unhealthy: 2,
    },
    agentHealth: {
      status: { status: 'degraded', message: '1 agent in stuck loop', lastChecked: ago(1) },
      total: 24,
      active: 19,
      stuck: 1,
      idle: 4,
    },
    graphHealth: {
      status: { status: 'healthy', message: 'Graph topology nominal', lastChecked: ago(2) },
      nodeCount: 14_832,
      edgeCount: 47_291,
      lastMutation: ago(4),
    },
    commandBrief: `SHIKI COMMAND BRIEF \u2014 ${now.toISOString().slice(0, 16)}Z

System posture: DEGRADED (2 issues)
\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

[P0] Notification service has been unreachable for 5 minutes.
     128 dispatch failures accumulated. Circuit breaker OPEN.
     Impact: No outbound alerts or digests being delivered.
     Recommended: Investigate notification-service pod health.

[P1] Redis write circuit breaker is HALF-OPEN after 3 failures.
     Cache latency elevated to 45ms (normal: 3-5ms).
     Impact: Slightly degraded read performance across all queries.
     Recommended: Monitor for recovery; escalate if not resolved in 10m.

[INFO] Throughput trending UP at 342 events/sec (24h avg: 330).
       Graph topology stable with 14,832 nodes / 47,291 edges.
       19 of 24 agents active, 1 stuck loop detected (enrichment-agent-04).
       2 customers flagged for help, 3 pending review batches.

Next actions: Review pending approval batch #47 (12 mutations staged).
              Investigate stuck agent enrichment-agent-04.
              Monitor notification service recovery.`,
    pendingApprovals: 3,
    activeAlerts: {
      total: 222,
      bySeverity: { P0: 128, P1: 69, P2: 15, P3: 8, info: 2 },
    },
    keyChanges1h: [
      { id: 'kc-1h-001', description: 'Notification service circuit breaker opened after 12 consecutive failures', severity: 'P0', timestamp: ago(5), controller: 'relay', entityType: 'service' },
      { id: 'kc-1h-002', description: 'Redis write latency spike to 45ms detected', severity: 'P1', timestamp: ago(10), controller: 'zeong' },
      { id: 'kc-1h-003', description: 'Agent enrichment-agent-04 entered stuck loop (8 retries)', severity: 'P1', timestamp: ago(8), controller: 'zeong', entityId: 'agent-enrich-04', entityType: 'agent' },
      { id: 'kc-1h-004', description: 'Customer acme-corp event stream interrupted for >15 minutes', severity: 'P0', timestamp: ago(15), controller: 'zeong', entityId: 'cust-acme-001', entityType: 'customer' },
      { id: 'kc-1h-005', description: 'Trust score drop for wallet 0x7a3b...f2e1 (0.82 \u2192 0.41)', severity: 'P2', timestamp: ago(25), controller: 'gouf', entityId: 'wallet-0x7a3b', entityType: 'wallet' },
    ],
    keyChanges24h: [
      { id: 'kc-24h-001', description: 'Review batch #45 approved and committed (8 mutations)', severity: 'info', timestamp: ago(180), controller: 'commit' },
      { id: 'kc-24h-002', description: 'New suspicious cluster C-892 identified by graph analysis', severity: 'P2', timestamp: ago(240), controller: 'gouf' },
      { id: 'kc-24h-003', description: 'Agent pool scaled from 20 to 24 to handle enrichment backlog', severity: 'info', timestamp: ago(360), controller: 'char' },
      { id: 'kc-24h-004', description: 'Customer beta-inc onboarding completed successfully', severity: 'info', timestamp: ago(420), controller: 'intake', entityId: 'cust-beta-002', entityType: 'customer' },
      { id: 'kc-24h-005', description: 'ClickHouse materialized view refresh delayed by 2 hours', severity: 'P3', timestamp: ago(600), controller: 'chronicle' },
      { id: 'kc-24h-006', description: 'Recovery controller reverted trust score adjustment on wallet 0x9f2a', severity: 'P2', timestamp: ago(720), controller: 'recovery', entityId: 'wallet-0x9f2a', entityType: 'wallet' },
      { id: 'kc-24h-007', description: 'Kafka consumer lag exceeded threshold briefly (resolved)', severity: 'P1', timestamp: ago(900), controller: 'zeong' },
    ],
    keyChanges7d: [
      { id: 'kc-7d-001', description: 'Major graph enrichment cycle completed (2,400 entities processed)', severity: 'info', timestamp: ago(2880), controller: 'gouf' },
      { id: 'kc-7d-002', description: 'Automation posture changed from conservative to balanced', severity: 'P2', timestamp: ago(4320), controller: 'governance' },
      { id: 'kc-7d-003', description: 'System-wide health recovered from P0 outage (postgres failover)', severity: 'P0', timestamp: ago(5760), controller: 'recovery' },
      { id: 'kc-7d-004', description: 'New controller relay deployed for notification routing', severity: 'info', timestamp: ago(7200), controller: 'char' },
      { id: 'kc-7d-005', description: '5 new customers onboarded in weekly batch', severity: 'info', timestamp: ago(8640), controller: 'intake' },
    ],
    recommendedActions: [
      {
        id: 'ra-001',
        title: 'Review pending approval batch #47',
        description: '12 entity mutations staged by Verification controller. 3 are Class 3 (operational). Batch has been waiting 15 minutes.',
        actionClass: 3,
        confidence: 0.92,
        reversible: true,
        controller: 'verification',
        rationale: 'Mutations are blocking downstream enrichment pipeline. Review cadence suggests immediate attention.',
      },
      {
        id: 'ra-002',
        title: 'Investigate stuck agent enrichment-agent-04',
        description: 'Agent has retried the same objective 8 times in 30 minutes with declining confidence. May need manual intervention or objective reset.',
        actionClass: 2,
        confidence: 0.87,
        reversible: true,
        controller: 'zeong',
        rationale: 'Stuck loop pattern detected. Enrichment pipeline backlog growing to 23 entities.',
        entityId: 'agent-enrich-04',
      },
      {
        id: 'ra-003',
        title: 'Monitor notification service recovery',
        description: 'Service has been unreachable for 5 minutes. Circuit breaker is OPEN with next retry in 2 minutes. If not recovered, escalate to infrastructure team.',
        actionClass: 1,
        confidence: 0.78,
        reversible: false,
        controller: 'relay',
        rationale: 'Critical communication path disrupted. 128 notifications queued.',
      },
      {
        id: 'ra-004',
        title: 'Review wallet 0x7a3b neighborhood in GOUF',
        description: 'Trust score dropped significantly after suspicious adjacency pattern. New edges connect to known cluster C-892.',
        actionClass: 2,
        confidence: 0.81,
        reversible: false,
        controller: 'gouf',
        rationale: 'Potential risk classification upgrade needed based on graph topology analysis.',
        entityId: 'wallet-0x7a3b',
      },
    ],
    customersNeedingHelp: [
      {
        entityId: 'cust-acme-001',
        entityType: 'customer',
        entityName: 'Acme Corp',
        reason: 'Event stream interrupted for >15 minutes',
        evidence: [
          'No events received since 14:32 UTC',
          'Last known SDK version: 2.1.3',
          'Previous interruption 3 days ago (resolved by SDK restart)',
        ],
        confidence: 0.94,
        recommendedAction: 'Contact customer to verify SDK integration status; check for network issues',
        reversible: false,
        owner: 'zeong',
        traceLink: '/entities/customer/cust-acme-001',
        severity: 'P0',
        flaggedAt: ago(15),
      },
      {
        entityId: 'cust-gamma-003',
        entityType: 'customer',
        entityName: 'Gamma Industries',
        reason: 'Anomalous event pattern detected (volume drop 73%)',
        evidence: [
          'Event volume dropped from 1,200/min to 320/min',
          'No configuration changes detected on our side',
          'Customer last active in dashboard 2 hours ago',
        ],
        confidence: 0.71,
        recommendedAction: 'Proactively reach out to customer; possible upstream data issue',
        reversible: false,
        traceLink: '/entities/customer/cust-gamma-003',
        severity: 'P1',
        flaggedAt: ago(45),
      },
    ],
    agentsNeedingHelp: [
      {
        entityId: 'agent-enrich-04',
        entityType: 'agent',
        entityName: 'enrichment-agent-04',
        reason: 'Stuck loop: 8 retries on same objective with declining confidence',
        evidence: [
          'Objective: "Enrich wallet 0x3f8a metadata from chain data"',
          'Confidence: 0.92 \u2192 0.34 over 8 attempts',
          'Each retry produces identical error: timeout on chain RPC call',
          'Backlog: 23 entities waiting for enrichment',
        ],
        confidence: 0.96,
        recommendedAction: 'Reset agent objective or mark entity for manual enrichment',
        reversible: true,
        owner: 'zeong',
        traceLink: '/entities/agent/agent-enrich-04',
        severity: 'P1',
        flaggedAt: ago(8),
      },
    ],
    recentInterventions: [
      {
        id: 'int-001',
        entityId: 'wallet-0x9f2a',
        type: 'revert',
        description: 'Reverted trust score adjustment on wallet 0x9f2a (false positive)',
        performedBy: 'Chief Engineer Amuro',
        performedAt: ago(720),
        reversible: false,
        revertId: 'rev-001',
        outcome: 'Trust score restored to 0.78',
      },
      {
        id: 'int-002',
        entityId: 'agent-enrich-02',
        type: 'manual-reset',
        description: 'Reset stuck agent enrichment-agent-02 objective queue',
        performedBy: 'Commander Bright',
        performedAt: ago(1440),
        reversible: true,
        outcome: 'Agent resumed normal operation',
      },
      {
        id: 'int-003',
        entityId: 'cust-delta-004',
        type: 'escalation',
        description: 'Escalated customer delta-004 support ticket to engineering',
        performedBy: 'Specialist Sayla',
        performedAt: ago(2160),
        reversible: false,
        outcome: 'Pending engineering review',
      },
      {
        id: 'int-004',
        entityId: 'batch-045',
        type: 'approval',
        description: 'Approved review batch #45 (8 graph mutations)',
        performedBy: 'Commander Bright',
        performedAt: ago(180),
        reversible: true,
        revertId: 'rev-045',
        outcome: 'All mutations committed successfully',
      },
    ],
  };
}
