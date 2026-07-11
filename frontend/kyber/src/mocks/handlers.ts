import { http, HttpResponse } from 'msw';

const API = '';
const now = () => new Date().toISOString();

// ── Helpers ────────────────────────────────────────────────────────────────────

function ok(data: unknown) {
  return HttpResponse.json({ data, status: 'ok', timestamp: now() });
}

function mockTenant(id: string, index: number) {
  const plans = ['P1', 'P2', 'P3', 'P4'];
  const statuses = ['active', 'active', 'active', 'suspended'];
  return {
    tenant_id: id,
    id,
    name: `Tenant ${index + 1}`,
    contact_email: `admin@tenant${index + 1}.io`,
    email: `admin@tenant${index + 1}.io`,
    plan: plans[index % 4],
    plan_tier: plans[index % 4],
    status: statuses[index % 4],
    created_at: new Date(Date.now() - (index + 1) * 30 * 86400_000).toISOString(),
    updated_at: new Date(Date.now() - index * 86400_000).toISOString(),
  };
}

const MOCK_TENANTS = Array.from({ length: 12 }, (_, i) => mockTenant(`tenant_${String(i + 1).padStart(3, '0')}`, i));

function mockApiKeys(tenantId: string) {
  return [
    { id: `key_${tenantId}_1`, name: 'Production', prefix: 'ak_prod', key_prefix: 'ak_prod', last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString() },
    { id: `key_${tenantId}_2`, name: 'Staging', prefix: 'ak_stg', key_prefix: 'ak_stg', last_used_at: null },
  ];
}

// ── Diagnostics ────────────────────────────────────────────────────────────────

const mockHealth = {
  status: 'healthy',
  uptime_seconds: 864_000,
  version: '0.9.4',
  services: { api: 'healthy', graph: 'healthy', kafka: 'healthy', redis: 'healthy', postgres: 'healthy' },
  computed_at: now(),
};

// ── Entities ───────────────────────────────────────────────────────────────────

const MOCK_ENTITIES = Array.from({ length: 20 }, (_, i) => ({
  id: `entity_${String(i + 1).padStart(4, '0')}`,
  kind: i % 3 === 0 ? 'agent' : i % 3 === 1 ? 'user' : 'org',
  label: `Entity ${i + 1}`,
  trust_score: Math.round(60 + Math.random() * 40),
  risk_level: ['low', 'medium', 'high'][i % 3],
  created_at: new Date(Date.now() - i * 7 * 86400_000).toISOString(),
}));

// ── CIS ────────────────────────────────────────────────────────────────────────

const mockCisHealth = {
  status: 'degraded',
  overall_status: 'degraded',
  active_mutations: 3,
  mutation_count: 3,
  drift_alert_count: 2,
  drift_alerts: 2,
  contamination_score: 0.12,
  contamination: 0.12,
  computed_at: now(),
};

const mockMutations = Array.from({ length: 5 }, (_, i) => ({
  mutation_id: `mut_${String(i + 1).padStart(4, '0')}`,
  id: `mut_${String(i + 1).padStart(4, '0')}`,
  mutation_type: ['schema_drift', 'value_injection', 'temporal_anomaly', 'graph_poisoning', 'retrieval_bias'][i],
  type: ['schema_drift', 'value_injection', 'temporal_anomaly', 'graph_poisoning', 'retrieval_bias'][i],
  severity: ['critical', 'high', 'medium', 'high', 'low'][i],
  node_id: `node_${String(i + 1).padStart(4, '0')}`,
  entity_id: `entity_${String(i + 1).padStart(4, '0')}`,
  status: ['active', 'active', 'quarantined', 'active', 'approved'][i],
  detected_at: new Date(Date.now() - i * 2 * 3600_000).toISOString(),
}));

const mockDriftAlerts = [
  { severity: 'high', title: 'Graph topology drift detected', description: 'Unexpected edge pattern in cluster C-007', node_id: 'node_0007', detected_at: new Date(Date.now() - 3600_000).toISOString() },
  { severity: 'medium', title: 'Retrieval score variance', description: 'P95 retrieval latency 3.2σ above baseline', detected_at: new Date(Date.now() - 7200_000).toISOString() },
];

// ── Investigations ─────────────────────────────────────────────────────────────

const MOCK_CASES = Array.from({ length: 4 }, (_, i) => ({
  case_id: `case_${String(i + 1).padStart(4, '0')}`,
  id: `case_${String(i + 1).padStart(4, '0')}`,
  title: ['Suspicious agent activity — cluster C-007', 'Graph poisoning attempt — user org_0012', 'Anomalous withdrawal pattern — agent_0034', 'Identity collision — user_0091'][i],
  status: ['active', 'triage', 'escalated', 'closed'][i],
  severity: ['critical', 'high', 'medium', 'low'][i],
  assigned_to: 'operator',
  created_at: new Date(Date.now() - (i + 1) * 3 * 86400_000).toISOString(),
  updated_at: new Date(Date.now() - i * 86400_000).toISOString(),
  description: 'Investigation opened by operator.',
  evidence: [],
  annotations: [],
  timeline: [
    { ts: new Date(Date.now() - (i + 1) * 3 * 86400_000).toISOString(), event: 'case_opened', actor: 'operator' },
  ],
}));

// ── Analytics / Mission ────────────────────────────────────────────────────────

const mockDashboard = {
  total_entities: 142_830,
  active_tenants: 38,
  events_last_24h: 2_847_291,
  graph_nodes: 892_110,
  graph_edges: 4_210_888,
  anomaly_score: 0.07,
  computed_at: now(),
};

const mockAgentStatus = {
  active_agents: 24,
  queued_tasks: 7,
  completed_tasks_24h: 183,
  failed_tasks_24h: 2,
  kill_switch: false,
};

// ── Agent ops — live command center (deterministic fixtures) ───────────────────

const mockAgentOpsHealth = {
  status: 'degraded',
  kill_switch: false,
  queue_depth: 12,
  worker_count: 4,
  stale_workers: 1,
  active_runs: 3,
  failed_runs: 2,
  stuck_runs: 1,
  computed_at: '2026-07-09T12:00:00.000Z',
};

const mockAgentControllersStatus = {
  controllers: [
    { name: 'nous', status: 'healthy', queue_depth: 4, last_heartbeat_at: '2026-07-09T11:59:30.000Z' },
    { name: 'catalyst', status: 'healthy', queue_depth: 6, last_heartbeat_at: '2026-07-09T11:59:10.000Z' },
    { name: 'intake', status: 'stale', queue_depth: 2, last_heartbeat_at: '2026-07-09T10:12:00.000Z' },
  ],
  count: 3,
};

const MOCK_AGENT_RUNS = [
  {
    run_id: 'run_001',
    tenant_id: 'tenant_001',
    objective_id: 'obj_001',
    controller: 'nous',
    queue: 'agent:runs:default',
    status: 'running',
    attempt: 1,
    created_at: '2026-07-09T11:40:00.000Z',
    updated_at: '2026-07-09T11:58:00.000Z',
    error: null,
  },
  {
    run_id: 'run_002',
    tenant_id: 'tenant_001',
    objective_id: 'obj_001',
    controller: 'catalyst',
    queue: 'agent:runs:default',
    status: 'completed',
    attempt: 1,
    created_at: '2026-07-09T10:00:00.000Z',
    updated_at: '2026-07-09T10:12:00.000Z',
    error: null,
  },
  {
    run_id: 'run_003',
    tenant_id: 'tenant_002',
    objective_id: 'obj_002',
    controller: 'intake',
    queue: 'agent:runs:priority',
    status: 'failed',
    attempt: 2,
    created_at: '2026-07-09T09:30:00.000Z',
    updated_at: '2026-07-09T09:45:00.000Z',
    error: 'worker crashed: out of memory during graph projection',
  },
  {
    run_id: 'run_004',
    tenant_id: 'tenant_001',
    objective_id: 'obj_003',
    controller: 'nous',
    queue: 'agent:runs:default',
    status: 'stale',
    attempt: 3,
    created_at: '2026-07-09T08:00:00.000Z',
    updated_at: '2026-07-09T08:20:00.000Z',
    error: 'heartbeat lost — no worker update for 45m',
  },
  {
    run_id: 'run_005',
    tenant_id: 'tenant_002',
    objective_id: 'obj_002',
    controller: 'catalyst',
    queue: 'agent:runs:default',
    status: 'queued',
    attempt: 1,
    created_at: '2026-07-09T11:55:00.000Z',
    updated_at: '2026-07-09T11:55:00.000Z',
    error: null,
  },
];

const MOCK_AGENT_BRIEFINGS = [
  {
    id: 'brief_001',
    tenant_id: 'tenant_001',
    type: 'run_complete',
    title: 'Objective obj_001 step completed',
    body: 'Catalyst finished enrichment pass: 42 entities updated, 0 staged mutations pending review.',
    created_at: '2026-07-09T10:12:30.000Z',
  },
  {
    id: 'brief_002',
    tenant_id: 'tenant_001',
    type: 'daily',
    title: 'Daily operator briefing',
    body: '3 active runs, 2 failed runs need triage, 1 stuck run awaiting recovery. Kill switch clear.',
    created_at: '2026-07-09T06:00:00.000Z',
  },
];

const MOCK_AGENT_OPS_ALERTS = [
  {
    id: 'ops_alert_001',
    severity: 'critical',
    kind: 'worker_stale',
    message: 'Worker heartbeat missing on queue agent:runs:default',
    count: 5,
    dedupe_key: 'worker_stale:agent:runs:default',
    first_seen_at: '2026-07-09T08:20:00.000Z',
    last_seen_at: '2026-07-09T11:50:00.000Z',
  },
  {
    id: 'ops_alert_002',
    severity: 'medium',
    kind: 'run_failed',
    message: 'Run run_003 failed after 2 attempts',
    count: 1,
    dedupe_key: 'run_failed:run_003',
    first_seen_at: '2026-07-09T09:45:00.000Z',
    last_seen_at: '2026-07-09T09:45:00.000Z',
  },
];

const MOCK_AGENT_REVIEW_BATCHES = [
  {
    batch_id: 'rb_001',
    tenant_id: 'tenant_001',
    objective_id: 'obj_001',
    controller: 'catalyst',
    status: 'pending',
    staged_mutation_count: 3,
    created_at: '2026-07-09T10:12:00.000Z',
    updated_at: '2026-07-09T10:12:00.000Z',
  },
  {
    batch_id: 'rb_002',
    tenant_id: 'tenant_002',
    objective_id: 'obj_002',
    controller: 'nous',
    status: 'approved',
    staged_mutation_count: 0,
    created_at: '2026-07-08T15:00:00.000Z',
    updated_at: '2026-07-08T16:30:00.000Z',
  },
];

// ── Resolution / Review ────────────────────────────────────────────────────────

const mockPendingDecisions = {
  decisions: Array.from({ length: 3 }, (_, i) => ({
    id: `dec_${String(i + 1).padStart(4, '0')}`,
    action_class: i + 1,
    description: ['Merge identity cluster', 'Flag entity for review', 'Escalate to human operator'][i],
    confidence: [0.92, 0.78, 0.85][i],
    entity_id: `entity_${String(i + 1).padStart(4, '0')}`,
    created_at: new Date(Date.now() - i * 3600_000).toISOString(),
  })),
  total: 3,
};

// ── External agent telemetry (fleet) ───────────────────────────────────────────
// Deterministic fixtures: fixed ISO timestamps, no Date.now()-derived values.

const MOCK_AGENT_TELEMETRY_DEPLOYMENTS = [
  {
    tenant_id: 'tenant_001',
    id: 'dep_discord_support_001',
    display_name: 'Support Bot — Discord',
    external_platform: 'discord_bot',
    environment: 'production',
    status: 'active',
    event_count_24h: 4210,
    accepted_count_24h: 4102,
    rejected_count_24h: 61,
    error_count_24h: 12,
    consent_blocked_count_24h: 35,
    health_score: 0.97,
    last_event_at: '2026-07-08T21:42:00.000Z',
  },
  {
    tenant_id: 'tenant_001',
    id: 'dep_shopify_concierge_002',
    display_name: 'Shopping Concierge — Shopify',
    external_platform: 'shopify_app',
    environment: 'production',
    status: 'paused',
    event_count_24h: 0,
    accepted_count_24h: 0,
    rejected_count_24h: 0,
    error_count_24h: 0,
    consent_blocked_count_24h: 0,
    health_score: null,
    last_event_at: '2026-07-06T16:05:00.000Z',
  },
  {
    tenant_id: 'tenant_002',
    id: 'dep_mcp_research_003',
    display_name: 'Research Assistant — MCP',
    external_platform: 'mcp_server',
    environment: 'staging',
    status: 'error',
    event_count_24h: 812,
    accepted_count_24h: 640,
    rejected_count_24h: 118,
    error_count_24h: 54,
    consent_blocked_count_24h: 0,
    health_score: 0.62,
    last_event_at: '2026-07-08T19:10:00.000Z',
  },
];

// ── Payment rail observability (fleet) ─────────────────────────────────────────
// Deterministic fixtures: fixed ISO timestamps, no Date.now()-derived values.

const MOCK_PAYMENT_RAILS_FLEET = {
  totals: {
    configured_tenants: 3,
    sessions_observed_24h: 1287,
    sessions_unresolved: 14,
    reconciliation_conflicts: 5,
  },
  providers: [
    {
      provider: 'privy',
      status: 'healthy',
      configured_tenants: 3,
      webhook_verified_24h: 640,
      webhook_rejected_24h: 2,
      sessions_observed_24h: 512,
      sessions_completed_24h: 488,
      sessions_failed_24h: 9,
      sessions_unresolved: 4,
      reconciliation_matched_rate: 0.982,
      reconciliation_conflicts: 0,
    },
    {
      provider: 'stripe',
      status: 'healthy',
      configured_tenants: 2,
      webhook_verified_24h: 410,
      webhook_rejected_24h: 6,
      sessions_observed_24h: 388,
      sessions_completed_24h: 351,
      sessions_failed_24h: 12,
      sessions_unresolved: 5,
      reconciliation_matched_rate: 0.941,
      reconciliation_conflicts: 1,
    },
    {
      provider: 'coinbase',
      status: 'degraded',
      configured_tenants: 2,
      webhook_verified_24h: 188,
      webhook_rejected_24h: 41,
      sessions_observed_24h: 244,
      sessions_completed_24h: 190,
      sessions_failed_24h: 28,
      sessions_unresolved: 5,
      reconciliation_matched_rate: 0.706,
      reconciliation_conflicts: 4,
    },
    {
      provider: 'moonpay',
      status: 'not_configured',
      configured_tenants: 0,
      webhook_verified_24h: 0,
      webhook_rejected_24h: 0,
      sessions_observed_24h: 0,
      sessions_completed_24h: 0,
      sessions_failed_24h: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: null,
      reconciliation_conflicts: 0,
    },
    {
      provider: 'bridge',
      status: 'healthy',
      configured_tenants: 1,
      webhook_verified_24h: 58,
      webhook_rejected_24h: 0,
      sessions_observed_24h: 143,
      sessions_completed_24h: 143,
      sessions_failed_24h: 0,
      sessions_unresolved: 0,
      reconciliation_matched_rate: 1,
      reconciliation_conflicts: 0,
    },
  ],
  tenants: [
    {
      tenant_id: 'tenant_001',
      providers_configured: 3,
      providers_degraded: 0,
      sessions_observed_24h: 733,
      sessions_unresolved: 4,
      reconciliation_conflicts: 0,
      status: 'healthy',
    },
    {
      tenant_id: 'tenant_002',
      providers_configured: 2,
      providers_degraded: 1,
      sessions_observed_24h: 411,
      sessions_unresolved: 8,
      reconciliation_conflicts: 4,
      status: 'degraded',
    },
    {
      tenant_id: 'tenant_003',
      providers_configured: 1,
      providers_degraded: 0,
      sessions_observed_24h: 143,
      sessions_unresolved: 2,
      reconciliation_conflicts: 1,
      status: 'healthy',
    },
  ],
};

const MOCK_PAYMENT_RAILS_TENANTS: Record<string, unknown> = {
  tenant_001: {
    tenant_id: 'tenant_001',
    providers: [
      {
        provider: 'privy',
        adapter: {
          status: 'configured',
          environment: 'production',
          webhook_configured: true,
          polling_configured: true,
          last_synced_at: '2026-07-08T23:45:00.000Z',
        },
        health: {
          status: 'healthy',
          webhook_verified_24h: 320,
          webhook_rejected_24h: 1,
          sessions_observed_24h: 256,
          sessions_completed_24h: 244,
          sessions_failed_24h: 4,
          sessions_unresolved: 2,
          reconciliation_matched_rate: 0.982,
          reconciliation_conflicts: 0,
          last_event_at: '2026-07-08T21:42:00.000Z',
        },
      },
      {
        provider: 'stripe',
        adapter: {
          status: 'configured',
          environment: 'production',
          webhook_configured: true,
          polling_configured: false,
          last_synced_at: '2026-07-08T23:40:00.000Z',
        },
        health: {
          status: 'healthy',
          webhook_verified_24h: 210,
          webhook_rejected_24h: 3,
          sessions_observed_24h: 194,
          sessions_completed_24h: 176,
          sessions_failed_24h: 6,
          sessions_unresolved: 2,
          reconciliation_matched_rate: 0.941,
          reconciliation_conflicts: 0,
          last_event_at: '2026-07-08T18:22:02.000Z',
        },
      },
    ],
  },
  tenant_002: {
    tenant_id: 'tenant_002',
    providers: [
      {
        provider: 'coinbase',
        adapter: {
          status: 'error',
          environment: 'production',
          webhook_configured: true,
          polling_configured: true,
          last_synced_at: '2026-07-08T22:10:00.000Z',
        },
        health: {
          status: 'degraded',
          webhook_verified_24h: 96,
          webhook_rejected_24h: 38,
          sessions_observed_24h: 131,
          sessions_completed_24h: 98,
          sessions_failed_24h: 22,
          sessions_unresolved: 5,
          reconciliation_matched_rate: 0.706,
          reconciliation_conflicts: 4,
          last_event_at: '2026-07-08T06:15:40.000Z',
        },
      },
    ],
  },
  tenant_003: {
    tenant_id: 'tenant_003',
    providers: [
      {
        provider: 'bridge',
        adapter: {
          status: 'configured',
          environment: 'production',
          webhook_configured: true,
          polling_configured: true,
          last_synced_at: '2026-07-08T23:00:00.000Z',
        },
        health: {
          status: 'healthy',
          webhook_verified_24h: 58,
          webhook_rejected_24h: 0,
          sessions_observed_24h: 143,
          sessions_completed_24h: 143,
          sessions_failed_24h: 0,
          sessions_unresolved: 2,
          reconciliation_matched_rate: 1,
          reconciliation_conflicts: 1,
          last_event_at: '2026-07-08T08:01:12.000Z',
        },
      },
    ],
  },
};

// ── AI outcome efficiency — fleet health ───────────────────────────────────────
// Deterministic fixtures: cross-tenant aggregates only. Unknown costs stay
// unknown (they are a coverage gap, never zero), and raw prompt/completion
// content is never present.
const MOCK_AI_EFFICIENCY_FLEET = {
  fact_count: 48210,
  cost_coverage: 0.91,
  unknown_cost_share: 0.09,
  tenants_observed: 3,
  detector_counts: {
    retry_waste: 4,
    model_overqualification: 2,
    deterministic_replacement_candidate: 1,
    cache_opportunity: 3,
    failed_workflow_concentration: 1,
  },
  tenants: [
    {
      tenant_id: 'tenant_001',
      fact_count: 26410,
      cost_coverage: 0.97,
      unknown_cost_share: 0.03,
      open_findings: 2,
      status: 'healthy',
    },
    {
      tenant_id: 'tenant_002',
      fact_count: 14580,
      cost_coverage: 0.72,
      unknown_cost_share: 0.28,
      open_findings: 6,
      status: 'degraded',
    },
    {
      tenant_id: 'tenant_003',
      fact_count: 7220,
      cost_coverage: 0.99,
      unknown_cost_share: 0.01,
      open_findings: 3,
      status: 'healthy',
    },
  ],
};

const MOCK_AI_EFFICIENCY_TENANTS: Record<string, unknown> = {
  tenant_001: {
    tenant_id: 'tenant_001',
    fact_count: 26410,
    cost_coverage: 0.97,
    unknown_cost_share: 0.03,
    workflow_count: 812,
    detector_counts: {
      retry_waste: 0,
      model_overqualification: 1,
      deterministic_replacement_candidate: 0,
      cache_opportunity: 1,
      failed_workflow_concentration: 0,
    },
    models: [
      { provider: 'openai', model: 'gpt-4o-mini', invocations: 18204 },
      { provider: 'anthropic', model: 'claude-sonnet-4', invocations: 8206 },
    ],
    findings: [
      { detector: 'model_overqualification', severity: 'medium', title: 'gpt-4o used for template filling' },
      { detector: 'cache_opportunity', severity: 'low', title: 'Repeated identical planning prompt prefix' },
    ],
  },
  tenant_002: {
    tenant_id: 'tenant_002',
    fact_count: 14580,
    cost_coverage: 0.72,
    unknown_cost_share: 0.28,
    workflow_count: 340,
    detector_counts: {
      retry_waste: 4,
      model_overqualification: 1,
      deterministic_replacement_candidate: 0,
      cache_opportunity: 0,
      failed_workflow_concentration: 1,
    },
    models: [
      { provider: 'openai', model: 'gpt-4o', invocations: 14580 },
    ],
    findings: [
      { detector: 'retry_waste', severity: 'high', title: 'Retry storms on gpt-4o support replies' },
      { detector: 'failed_workflow_concentration', severity: 'high', title: 'Failed-execution cost concentrated in one workflow' },
    ],
  },
  tenant_003: {
    tenant_id: 'tenant_003',
    fact_count: 7220,
    cost_coverage: 0.99,
    unknown_cost_share: 0.01,
    workflow_count: 96,
    detector_counts: {
      retry_waste: 0,
      model_overqualification: 0,
      deterministic_replacement_candidate: 1,
      cache_opportunity: 2,
      failed_workflow_concentration: 0,
    },
    models: [
      { provider: 'mistral', model: 'mistral-embed', invocations: 7220 },
    ],
    findings: [
      { detector: 'deterministic_replacement_candidate', severity: 'medium', title: 'Currency formatting handled by LLM' },
      { detector: 'cache_opportunity', severity: 'low', title: 'Repeated identical catalog embedding prompts' },
    ],
  },
};

// ── Cluster Targeting Intelligence (fleet diagnostics, deterministic) ─────────
// camelCase per the targeting-intelligence contracts. Aether observes cluster
// targeting; recompute never mutates external campaign platforms.

const MOCK_TARGETING_FLEET_HEALTH = {
  tenantsObserved: 2,
  intentCount: 3,
  snapshotCount: 5,
  leakageBySeverity: { critical: 1, high: 2, medium: 1 },
  intentsBySource: { tenant_declared: 2, suggestion_generated: 1 },
};

const MOCK_TARGETING_LEAKAGE_QUEUE = [
  {
    findingId: 'ti_leak_001',
    tenantId: 'tenant_001',
    campaignId: 'camp_spring_launch_001',
    clusterId: 'cluster_z',
    severity: 'critical',
    leakageRate: 0.21,
    reasonCode: 'fraud_risk',
    likelyCauses: ['provider_ignored_exclusion', 'lookalike_expansion'],
    computedAt: '2026-07-08T12:00:00.000Z',
  },
  {
    findingId: 'ti_leak_002',
    tenantId: 'tenant_002',
    campaignId: 'camp_renewal_005',
    clusterId: 'cluster_t',
    severity: 'high',
    leakageRate: 0.09,
    reasonCode: 'consent_blocked',
    likelyCauses: ['identity_resolved_after_launch'],
    computedAt: '2026-07-07T09:00:00.000Z',
  },
];

const MOCK_TARGETING_MAPPING_QUALITY = [
  {
    tenantId: 'tenant_002',
    campaignId: 'camp_renewal_005',
    provider: 'google_ads',
    qualityScore: 0.34,
    blocksSuggestions: true,
    providerSyncFreshness: 'stale',
    reasons: ['unresolved provider aliases above threshold'],
    computedAt: '2026-07-07T09:00:00.000Z',
  },
  {
    tenantId: 'tenant_001',
    campaignId: 'camp_spring_launch_001',
    provider: 'meta_ads',
    qualityScore: 0.87,
    blocksSuggestions: false,
    providerSyncFreshness: 'recent',
    reasons: [],
    computedAt: '2026-07-08T12:00:00.000Z',
  },
];

const MOCK_TARGETING_RELEASE_READINESS = {
  ready: false,
  checks: [
    { name: 'contracts_importable', passed: true, detail: '' },
    { name: 'non_execution_invariant', passed: true, detail: '' },
    { name: 'policy_deterministic_consent_wins', passed: true, detail: '' },
    { name: 'stores_reachable', passed: false, detail: 'targeting_audit store unreachable' },
  ],
  flags: {
    enabled: true,
    exports_enabled: true,
    ooda_suggestions_enabled: false,
    kyber_enabled: true,
  },
};

const MOCK_TARGETING_AUDIT = [
  {
    id: 'aud_ti_001',
    tenantId: 'tenant_001',
    action: 'snapshot_recomputed',
    actor: 'kyber-operator',
    detail: { intentId: 'ti_intent_001', asOf: '2026-07-02T00:00:00.000Z' },
    occurredAt: '2026-07-09T10:00:00.000Z',
  },
  {
    id: 'aud_ti_002',
    tenantId: 'tenant_002',
    action: 'leakage_recomputed',
    actor: 'kyber-operator',
    detail: { observationId: 'ti_obs_005' },
    occurredAt: '2026-07-08T16:00:00.000Z',
  },
];

// ── Tenant Import Engine ops ─────────────────────────────────────────────────

const MOCK_IMPORT_SESSIONS = [
  {
    id: 'imp_20260711_0007', tenant_id: 'tenant_003', status: 'failed', source_kind: 'file_upload',
    file_count: 2, row_count: 48210, created_by: 'ingest@tenant3.io',
    created_at: '2026-07-11T09:12:00.000Z', updated_at: '2026-07-11T09:18:44.000Z',
  },
  {
    id: 'imp_20260711_0006', tenant_id: 'tenant_001', status: 'committed', source_kind: 'file_upload',
    file_count: 1, row_count: 12904, created_by: 'ops@tenant1.io',
    created_at: '2026-07-11T08:40:00.000Z', updated_at: '2026-07-11T08:52:10.000Z',
  },
  {
    id: 'imp_20260710_0005', tenant_id: 'tenant_007', status: 'review_required', source_kind: 'file_upload',
    file_count: 3, row_count: 90311, created_by: 'data@tenant7.io',
    created_at: '2026-07-10T22:05:00.000Z', updated_at: '2026-07-10T22:31:02.000Z',
  },
  {
    id: 'imp_20260710_0004', tenant_id: 'tenant_002', status: 'committing', source_kind: 'file_upload',
    file_count: 1, row_count: null, created_by: null,
    created_at: '2026-07-10T19:44:00.000Z', updated_at: '2026-07-10T19:45:12.000Z',
  },
  {
    id: 'imp_20260709_0003', tenant_id: 'tenant_005', status: 'partially_committed', source_kind: 'file_upload',
    file_count: 4, row_count: 210044, created_by: 'admin@tenant5.io',
    created_at: '2026-07-09T14:00:00.000Z', updated_at: '2026-07-09T14:39:55.000Z',
  },
];

const MOCK_IMPORT_COMMITS: Record<string, Array<Record<string, unknown>>> = {
  imp_20260711_0007: [
    {
      id: 'cmt_0007_a', commit_id: 'cmt_0007_a', import_id: 'imp_20260711_0007', status: 'failed',
      row_count: 48210, vertices_count: 0, edges_count: 0, rolled_back: true,
      created_at: '2026-07-11T09:18:40.000Z', created_by: 'ingest@tenant3.io',
    },
  ],
  imp_20260711_0006: [
    {
      id: 'cmt_0006_a', commit_id: 'cmt_0006_a', import_id: 'imp_20260711_0006', status: 'committed',
      row_count: 12904, vertices_count: 12904, edges_count: 25808, rolled_back: false,
      created_at: '2026-07-11T08:52:05.000Z', created_by: 'ops@tenant1.io',
    },
  ],
  imp_20260709_0003: [
    {
      id: 'cmt_0003_a', commit_id: 'cmt_0003_a', import_id: 'imp_20260709_0003', status: 'committed',
      row_count: 140000, vertices_count: 140000, edges_count: 280000, rolled_back: false,
      created_at: '2026-07-09T14:30:00.000Z', created_by: 'admin@tenant5.io',
    },
    {
      id: 'cmt_0003_b', commit_id: 'cmt_0003_b', import_id: 'imp_20260709_0003', status: 'failed',
      row_count: 70044, vertices_count: 0, edges_count: 0, rolled_back: true,
      created_at: '2026-07-09T14:39:50.000Z', created_by: 'admin@tenant5.io',
    },
  ],
};

// ── Handlers ───────────────────────────────────────────────────────────────────

export const handlers = [
  // Auth
  http.post(`${API}/v1/auth/login`, async ({ request }) => {
    const body = await request.json() as { email?: string };
    return ok({ access_token: 'mock_access_token', refresh_token: 'mock_refresh_token', expires_in: 3600, email: body.email });
  }),
  http.post(`${API}/v1/auth/token`, () => ok({ access_token: 'mock_access_token', refresh_token: 'mock_refresh_token', expires_in: 3600 })),
  http.post(`${API}/v1/auth/refresh`, () => ok({ access_token: 'mock_access_token_refreshed', expires_in: 3600 })),

  // Diagnostics / health
  http.get(`${API}/v1/diagnostics/health`, () => ok(mockHealth)),
  http.get(`${API}/v1/diagnostics/report`, () => ok({ health: mockHealth, errors: [], circuit_breakers: [] })),
  http.get(`${API}/v1/diagnostics/errors`, () => ok({ errors: [], count: 0 })),
  http.get(`${API}/v1/diagnostics/circuit-breakers`, () => ok({ circuit_breakers: [] })),
  http.get(`${API}/v1/diagnostics/sdk/health`, () => ok({ sdks: [], count: 0 })),

  // Analytics / Mission
  http.get(`${API}/v1/analytics/dashboard/summary`, () => ok(mockDashboard)),
  http.post(`${API}/v1/analytics/graphql`, () => ok({ data: {} })),
  http.get(`${API}/v1/analytics/events`, () => ok({ events: [], count: 0 })),

  // Agent status / Review
  http.get(`${API}/v1/agent/status`, () => ok(mockAgentStatus)),
  http.get(`${API}/v1/agent/audit`, () => ok({ tasks: [], count: 0 })),
  http.post(`${API}/v1/agent/tasks`, () => ok({ task_id: 'task_mock', status: 'queued' })),
  http.post(`${API}/v1/agent/kill-switch`, async ({ request }) => {
    const body = await request.json() as { action?: string };
    const action = body?.action ?? 'engage';
    return ok({ kill_switch: action === 'engage', action });
  }),

  // Agent ops — live command center
  http.get(`${API}/v1/agent/health`, () => ok(mockAgentOpsHealth)),
  http.get(`${API}/v1/agent/controllers/status`, () => ok(mockAgentControllersStatus)),
  http.get(`${API}/v1/agent/runs`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const objectiveId = url.searchParams.get('objective_id');
    let runs = MOCK_AGENT_RUNS;
    if (status) runs = runs.filter(r => r.status === status);
    if (objectiveId) runs = runs.filter(r => r.objective_id === objectiveId);
    return ok({ runs });
  }),
  http.get(`${API}/v1/agent/runs/stuck`, () =>
    ok({ runs: MOCK_AGENT_RUNS.filter(r => r.status === 'stale') }),
  ),
  http.get(`${API}/v1/agent/briefings`, () => ok({ briefings: MOCK_AGENT_BRIEFINGS })),
  http.post(`${API}/v1/agent/briefings/generate`, () =>
    ok({ briefing: { ...MOCK_AGENT_BRIEFINGS[1], id: 'brief_generated_001', type: 'handoff', title: 'Operator handoff briefing' }, generated: true }),
  ),
  http.get(`${API}/v1/agent/ops/alerts`, () => ok({ alerts: MOCK_AGENT_OPS_ALERTS })),
  http.get(`${API}/v1/agent/review-batches`, () => ok({ batches: MOCK_AGENT_REVIEW_BATCHES, count: MOCK_AGENT_REVIEW_BATCHES.length })),
  http.post(`${API}/v1/agent/review-batches/:batchId/approve`, ({ params }) =>
    ok({ batch_id: params.batchId, status: 'approved' }),
  ),
  http.post(`${API}/v1/agent/review-batches/:batchId/reject`, ({ params }) =>
    ok({ batch_id: params.batchId, status: 'rejected' }),
  ),

  // Automation
  http.get(`${API}/v1/automation/insights`, () => ok({ insights: [], count: 0 })),

  // Intelligence alerts
  http.get(`${API}/v1/intelligence/alerts`, () => ok({ alerts: [], count: 0 })),

  // Entities
  http.get(`${API}/v1/entities`, () => ok({ entities: MOCK_ENTITIES, total: MOCK_ENTITIES.length })),
  http.get(`${API}/v1/entities/search`, () => ok({ results: MOCK_ENTITIES.slice(0, 5), total: 5 })),
  http.get(`${API}/v1/entities/:entityId`, ({ params }) => ok({ ...MOCK_ENTITIES[0], id: params.entityId, entity_id: params.entityId })),
  http.get(`${API}/v1/entities/:entityId/graph`, ({ params }) =>
    ok({ entity_id: params.entityId, nodes: [], edges: [], node_count: 0, edge_count: 0 }),
  ),

  // Resolution / Review queue
  http.get(`${API}/v1/resolution/pending`, () => ok(mockPendingDecisions)),
  http.post(`${API}/v1/resolution/pending/:decisionId/approve`, () => ok({ approved: true })),
  http.post(`${API}/v1/resolution/pending/:decisionId/reject`, () => ok({ rejected: true })),
  http.get(`${API}/v1/resolution/audit/:decisionId`, () => ok({ audit: [] })),

  // Admin — tenants
  http.get(`${API}/v1/admin/tenants`, () => HttpResponse.json({ data: { tenants: MOCK_TENANTS, total: MOCK_TENANTS.length }, status: 'ok', timestamp: now() })),
  http.post(`${API}/v1/admin/tenants`, async ({ request }) => {
    const body = await request.json() as { name: string; plan: string };
    return ok({ ...mockTenant(`tenant_new_${Date.now()}`, 99), name: body.name, plan: body.plan });
  }),
  http.get(`${API}/v1/admin/tenants/:tenantId`, ({ params }) => {
    const t = MOCK_TENANTS.find(x => x.id === params.tenantId) ?? mockTenant(String(params.tenantId), 0);
    return ok(t);
  }),
  http.patch(`${API}/v1/admin/tenants/:tenantId`, async ({ params, request }) => {
    const body = await request.json() as Record<string, unknown>;
    const t = MOCK_TENANTS.find(x => x.id === params.tenantId) ?? mockTenant(String(params.tenantId), 0);
    return ok({ ...t, ...body });
  }),
  http.post(`${API}/v1/admin/tenants/:tenantId/deactivate`, ({ params }) =>
    ok({ tenant_id: params.tenantId, status: 'deactivated' }),
  ),
  http.delete(`${API}/v1/admin/tenants/:tenantId`, ({ params }) =>
    ok({ tenant_id: params.tenantId, deleted: true }),
  ),

  // Admin — API keys
  http.get(`${API}/v1/admin/tenants/:tenantId/api-keys`, ({ params }) =>
    HttpResponse.json(mockApiKeys(String(params.tenantId))),
  ),
  http.post(`${API}/v1/admin/tenants/:tenantId/api-keys`, async ({ params, request }) => {
    const body = await request.json() as { name: string };
    return ok({ id: `key_new_${Date.now()}`, name: body.name, prefix: 'ak_new', tenant_id: params.tenantId });
  }),
  http.delete(`${API}/v1/admin/api-keys/:keyId`, ({ params }) =>
    ok({ revoked: true, id: params.keyId }),
  ),

  // Admin — billing
  http.get(`${API}/v1/admin/tenants/:tenantId/billing`, ({ params }) =>
    ok({
      tenant_id: params.tenantId,
      status: 'active',
      subscription_status: 'active',
      plan_name: 'Professional',
      mrr: 499,
      current_period_start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString(),
      current_period_end: new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).toISOString(),
    }),
  ),
  http.get(`${API}/v1/admin/tenants/:tenantId/billing/usage`, ({ params }) =>
    ok({ tenant_id: params.tenantId, events_this_period: 73_450, monthly_events: 73_450, events_quota: 100_000, computed_at: now() }),
  ),
  http.get(`${API}/v1/admin/tenants/:tenantId/billing/invoices`, ({ params }) =>
    ok({
      tenant_id: params.tenantId,
      invoices: [
        { id: 'inv_001', amount: 49900, status: 'paid', created_at: new Date(Date.now() - 30 * 86400_000).toISOString(), date: new Date(Date.now() - 30 * 86400_000).toISOString() },
        { id: 'inv_002', amount: 49900, status: 'paid', created_at: new Date(Date.now() - 60 * 86400_000).toISOString(), date: new Date(Date.now() - 60 * 86400_000).toISOString() },
      ],
      count: 2,
    }),
  ),

  // CIS
  http.get(`${API}/v1/cis/health/global`, () => ok(mockCisHealth)),
  http.get(`${API}/v1/cis/health`, () => ok(mockCisHealth)),
  http.get(`${API}/v1/cis/mutations`, () => ok({ mutations: mockMutations })),
  http.post(`${API}/v1/cis/mutations/:mutationId/quarantine`, ({ params }) =>
    ok({ mutation_id: params.mutationId, status: 'quarantined' }),
  ),
  http.post(`${API}/v1/cis/mutations/:mutationId/approve`, ({ params }) =>
    ok({ mutation_id: params.mutationId, status: 'approved' }),
  ),
  http.get(`${API}/v1/cis/forensics/:nodeId`, ({ params }) =>
    ok({
      node_id: params.nodeId,
      node_type: 'entity',
      kind: 'entity',
      trust_score: 72,
      risk_level: 'medium',
      risk: 'medium',
      signals: [
        { severity: 'high', signal: 'unexpected_edge_pattern', name: 'unexpected_edge_pattern', score: 0.88 },
        { severity: 'medium', signal: 'retrieval_latency_spike', name: 'retrieval_latency_spike', score: 0.61 },
      ],
      timeline: [
        { ts: new Date(Date.now() - 3600_000).toISOString(), event: 'anomaly_detected', action: 'anomaly_detected' },
        { ts: new Date(Date.now() - 7200_000).toISOString(), event: 'node_flagged', action: 'node_flagged' },
      ],
    }),
  ),
  http.get(`${API}/v1/cis/drift`, () => ok({ alerts: mockDriftAlerts })),
  http.get(`${API}/v1/cis/contamination`, () => ok({ score: 0.12, threshold: 0.25, status: 'ok' })),
  http.get(`${API}/v1/cis/retrieval`, () => ok({ items: [], count: 0 })),
  http.get(`${API}/v1/cis/reasoning`, () => ok({ chains: [], count: 0 })),

  // Dune feeder
  http.get(`${API}/v1/admin/dune-feeder/health`, () => ok({
    status: 'ok',
    total_bronze_records: 0,
    total_silver_records: 0,
    total_gold_records: 0,
    unique_source_tags: 0,
    rejection_rate: 0,
    last_ingest_at: null,
    last_ingest_source_tag: null,
    graph_isolation_enforced: true,
  })),
  http.get(`${API}/v1/admin/dune-feeder/gold`, () => ok({ records: [], record_count: 0 })),
  http.post(`${API}/v1/admin/dune-feeder/ingest`, () => ok({ rows_submitted: 0, rows_accepted: 0, rows_rejected: 0, source_tag: '' })),
  http.post(`${API}/v1/admin/dune-feeder/rollback`, () => ok({ source_tag: '', records_deleted: 0 })),
  http.post(`${API}/v1/admin/dune-feeder/promote/:source_tag`, ({ params }) => ok({ source_tag: params.source_tag, rows_promoted: 0 })),
  http.post(`${API}/v1/admin/dune-feeder/materialize-gold`, () => ok({ source_tag: '', gold_records_created: 0 })),
  http.get(`${API}/v1/admin/dune-feeder/audit/:source_tag`, ({ params }) => ok({ source_tag: params.source_tag, tenant_scope: null, record_count: 0, records: [] })),

  // Investigations
  http.get(`${API}/v1/investigations`, () => ok({ investigations: MOCK_CASES, cases: MOCK_CASES, count: MOCK_CASES.length })),
  http.post(`${API}/v1/investigations`, async ({ request }) => {
    const body = await request.json() as { title: string };
    return ok({ case_id: `case_new_${Date.now()}`, id: `case_new_${Date.now()}`, title: body.title, status: 'open', created_at: now() });
  }),
  http.get(`${API}/v1/investigations/:caseId`, ({ params }) => {
    const c = MOCK_CASES.find(x => x.id === params.caseId) ?? MOCK_CASES[0];
    return ok(c);
  }),
  http.patch(`${API}/v1/investigations/:caseId/status`, ({ params }) =>
    ok({ case_id: params.caseId, updated: true }),
  ),
  http.post(`${API}/v1/investigations/:caseId/evidence`, ({ params }) =>
    ok({ case_id: params.caseId, added: true }),
  ),
  http.post(`${API}/v1/investigations/:caseId/annotations`, ({ params }) =>
    ok({ case_id: params.caseId, annotation_id: `ann_${Date.now()}`, created: true }),
  ),

  // External agent telemetry — fleet observability (deterministic fixtures)
  http.get(`${API}/v1/admin/kyber/agent-telemetry/deployments`, () =>
    ok({
      total_deployments: MOCK_AGENT_TELEMETRY_DEPLOYMENTS.length,
      active_deployments: MOCK_AGENT_TELEMETRY_DEPLOYMENTS.filter(d => d.status === 'active').length,
      tenants_with_deployments: 2,
      events_24h: 5022,
      counts_by_status: { active: 1, paused: 1, error: 1 },
      counts_by_platform: { discord_bot: 1, shopify_app: 1, mcp_server: 1 },
      deployments: MOCK_AGENT_TELEMETRY_DEPLOYMENTS,
    }),
  ),
  http.get(`${API}/v1/admin/kyber/agent-telemetry/deployments/:tenantId/:deploymentId`, ({ params }) => {
    const deployment = MOCK_AGENT_TELEMETRY_DEPLOYMENTS.find(
      d => d.tenant_id === params.tenantId && d.id === params.deploymentId,
    );
    if (!deployment) {
      return HttpResponse.json({ message: 'Deployment not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return ok({
      deployment: {
        ...deployment,
        environment: 'production',
        consent_mode: 'platform_managed',
        last_event_at: '2026-07-08T21:42:00.000Z',
      },
      health: {
        event_count_24h: deployment.event_count_24h,
        accepted_count_24h: deployment.accepted_count_24h,
        rejected_count_24h: deployment.rejected_count_24h,
        error_count_24h: deployment.error_count_24h,
        consent_blocked_count_24h: deployment.consent_blocked_count_24h,
        health_score: deployment.health_score,
      },
      diagnostics: {
        rejection_reasons: { schema_validation_failed: 42, unknown_event_family: 19 },
        consent_block_rate: 0.008,
        ingest_lag_ms: 240,
        last_error: deployment.status === 'error' ? 'capability scope mismatch: observe:payments not granted' : null,
      },
      recent_activity: [
        { id: 'act_001', action: 'created', actor: 'tenant-admin', occurred_at: '2026-05-01T14:00:00.000Z' },
        { id: 'act_002', action: 'updated', actor: 'tenant-admin', occurred_at: '2026-07-01T10:30:00.000Z' },
      ],
    });
  }),

  // Payment rail observability — fleet health (deterministic fixtures)
  http.get(`${API}/v1/admin/kyber/payment-rails/health`, () => ok(MOCK_PAYMENT_RAILS_FLEET)),
  http.get(`${API}/v1/admin/kyber/payment-rails/:tenantId`, ({ params }) => {
    const diagnostics = MOCK_PAYMENT_RAILS_TENANTS[String(params.tenantId)];
    if (!diagnostics) {
      return HttpResponse.json({ message: 'Tenant not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return ok(diagnostics);
  }),

  // AI outcome efficiency — fleet health (deterministic fixtures)
  http.get(`${API}/v1/admin/kyber/ai-efficiency/health`, () => ok(MOCK_AI_EFFICIENCY_FLEET)),
  http.get(`${API}/v1/admin/kyber/ai-efficiency/:tenantId`, ({ params }) => {
    const drilldown = MOCK_AI_EFFICIENCY_TENANTS[String(params.tenantId)];
    if (!drilldown) {
      return HttpResponse.json({ message: 'Tenant not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return ok(drilldown);
  }),

  // Cluster Targeting Intelligence — fleet diagnostics (deterministic fixtures)
  http.get(`${API}/v1/admin/kyber/targeting/health`, () => ok(MOCK_TARGETING_FLEET_HEALTH)),
  http.get(`${API}/v1/admin/kyber/targeting/leakage-queue`, ({ request }) => {
    const severity = new URL(request.url).searchParams.get('severity');
    const queue = severity
      ? MOCK_TARGETING_LEAKAGE_QUEUE.filter(f => f.severity === severity)
      : MOCK_TARGETING_LEAKAGE_QUEUE;
    return ok({ queue });
  }),
  http.get(`${API}/v1/admin/kyber/targeting/mapping-quality`, () =>
    ok({ diagnostics: MOCK_TARGETING_MAPPING_QUALITY }),
  ),
  http.post(`${API}/v1/admin/kyber/targeting/recompute`, async ({ request }) => {
    const body = await request.json() as { tenantId?: string; intentId?: string; asOf?: string; observationId?: string };
    if (body.intentId && body.asOf) {
      return ok({
        recomputed: 'snapshot',
        snapshot: {
          snapshotId: 'ti_snap_recomputed_001',
          tenantId: body.tenantId,
          targetingIntentId: body.intentId,
          asOf: body.asOf,
          createdAt: '2026-07-09T10:00:00.000Z',
        },
      });
    }
    if (body.observationId) {
      return ok({ recomputed: 'leakage', findings: MOCK_TARGETING_LEAKAGE_QUEUE.slice(0, 1) });
    }
    return HttpResponse.json(
      { message: 'Provide intentId+asOf (snapshot) or observationId (leakage)', code: 'BAD_REQUEST' },
      { status: 400 },
    );
  }),
  http.get(`${API}/v1/admin/kyber/targeting/release-readiness`, () => ok(MOCK_TARGETING_RELEASE_READINESS)),
  http.get(`${API}/v1/admin/kyber/targeting/audit`, () => ok({ audit: MOCK_TARGETING_AUDIT })),

  // ── Tenant Import Engine ops (cross-tenant) ──────────────────────────────────
  http.get(`${API}/v1/kyber/imports/timeline`, ({ request }) => {
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get('limit') ?? '0');
    const sessions = limit > 0 ? MOCK_IMPORT_SESSIONS.slice(0, limit) : MOCK_IMPORT_SESSIONS;
    return ok({ count: sessions.length, sessions });
  }),
  http.get(`${API}/v1/kyber/imports/:importId`, ({ params }) => {
    const importId = String(params.importId);
    const session = MOCK_IMPORT_SESSIONS.find(s => s.id === importId) ?? {
      ...MOCK_IMPORT_SESSIONS[0],
      id: importId,
    };
    const commits = MOCK_IMPORT_COMMITS[importId] ?? [];
    return ok({ session, commits, commit_count: commits.length });
  }),
  http.post(`${API}/v1/kyber/imports/:importId/requeue`, ({ params }) => {
    const importId = String(params.importId);
    return ok({ import_id: importId, job: { id: `job_${importId}`, status: 'queued' } });
  }),
];
