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
  http.post(`${API}/v1/agent/kill-switch`, () => ok({ kill_switch: true })),

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
];
