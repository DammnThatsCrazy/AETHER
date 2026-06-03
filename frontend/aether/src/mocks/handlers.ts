import { http, HttpResponse } from 'msw';

// Requests use relative paths (/v1/...) which resolve to the Vite dev server origin.
const API = '';

const mockProfile = {
  data: {
    tenant_id: 'tenant_demo_001',
    name: 'Alex Reeves',
    contact_email: 'alex@acme.io',
    email: 'alex@acme.io',
    plan: {
      plan_id: 'P2',
      display_name: 'Professional',
      monthly_quota: 100_000,
      burst_rpm: 500,
    },
    billing: {
      subscription_status: 'active',
      current_period_end: new Date(Date.now() + 12 * 86400 * 1000).toISOString(),
      stripe_customer_id: 'cus_mock',
    },
    api_key_count: 3,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockUsage = {
  data: {
    period_start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString(),
    period_end: new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).toISOString(),
    events_used: 73_450,
    events_quota: 100_000,
    rpm_peak: 182,
    rpm_limit: 500,
    overage_events: 0,
    days_remaining: 12,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockApiKeys = {
  data: {
    tenant_id: 'tenant_demo_001',
    api_keys: [
      { id: 'key_001', name: 'Production SDK', tier: 'P2', permissions: ['read', 'ingest'], last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString() },
      { id: 'key_002', name: 'Analytics Dashboard', tier: 'P2', permissions: ['read', 'analytics'], last_used_at: new Date(Date.now() - 3 * 86400_000).toISOString() },
      { id: 'key_003', name: 'Staging', tier: 'P2', permissions: ['read', 'write', 'ingest'], last_used_at: null },
    ],
    count: 3,
    total: 3,
    limit: 20,
    offset: 0,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockPlans = {
  data: {
    plans: [
      { plan_id: 'P1', display_name: 'Hobbyist', price_monthly: 99, monthly_quota: 25_000, burst_rpm: 100, features: ['10 services', 'Community support', 'Web SDK'] },
      { plan_id: 'P2', display_name: 'Professional', price_monthly: 499, monthly_quota: 100_000, burst_rpm: 500, features: ['19 services', 'Email support', 'All SDKs', 'Analytics dashboard'] },
      { plan_id: 'P3', display_name: 'Growth Intelligence', price_monthly: 1499, monthly_quota: 250_000, burst_rpm: 1200, features: ['29 services', 'Priority support', 'ML models', 'Campaign intelligence'] },
      { plan_id: 'P4', display_name: 'Protocol Master', price_monthly: 3999, monthly_quota: 500_000, burst_rpm: 3000, features: ['34 services', 'Dedicated support', 'Custom SLAs', 'Agent layer'] },
    ],
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockInvoices = {
  data: {
    invoices: [
      { id: 'inv_001', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-04-01', period_end: '2026-04-30', invoice_url: null },
      { id: 'inv_002', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-03-01', period_end: '2026-03-31', invoice_url: null },
      { id: 'inv_003', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-02-01', period_end: '2026-02-28', invoice_url: null },
    ],
    count: 3,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

export const handlers = [
  http.get(`${API}/v1/me`, () => HttpResponse.json(mockProfile)),
  http.get(`${API}/v1/me/usage`, () => HttpResponse.json(mockUsage)),
  http.get(`${API}/v1/me/api-keys`, () => HttpResponse.json(mockApiKeys)),
  http.delete(`${API}/v1/me/api-keys/:id`, ({ params }) =>
    HttpResponse.json({ data: { revoked: true, id: params.id }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/me/api-keys`, async ({ request }) => {
    const body = await request.json() as { name: string; permissions?: string[] };
    return HttpResponse.json({
      data: {
        api_key: `ak_${Math.random().toString(36).slice(2, 26)}`,
        key: `ak_${Math.random().toString(36).slice(2, 26)}`,
        id: `key_new_${Date.now()}`,
        name: body.name,
        tier: 'P2',
        permissions: body.permissions ?? ['read'],
        message: 'Store this key securely — it will not be shown again.',
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    });
  }),
  http.get(`${API}/v1/billing/plans`, () => HttpResponse.json(mockPlans)),
  http.get(`${API}/v1/billing/invoices`, () => HttpResponse.json(mockInvoices)),
  http.post(`${API}/v1/billing/checkout`, () =>
    HttpResponse.json({ data: { session_id: 'cs_mock', url: '', mocked: true }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/billing/portal`, () =>
    HttpResponse.json({ data: { url: '', mocked: true }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/contact/enterprise`, () =>
    HttpResponse.json({ data: { received: true, message: "Thank you — we'll be in touch within 2 business days." }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/register`, async ({ request }) => {
    const body = await request.json() as { email?: string };
    return HttpResponse.json({ data: { message: 'Check your email for a verification code.', email: body.email ?? 'user@example.com' }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.post(`${API}/v1/auth/verify-email`, () =>
    HttpResponse.json({ data: { api_key: 'ak_mock_dev_key_from_otp_verify', tenant_id: 'tenant_demo_001', name: 'Alex Reeves', message: 'Verified' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/login`, async ({ request }) => {
    const body = await request.json() as { email?: string };
    return HttpResponse.json({ data: { api_key: 'ak_mock_login_key', tenant_id: 'tenant_demo_001', email: body.email }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/billing/plans`, () => HttpResponse.json(mockPlans)),

  // ── Users / entities ─────────────────────────────────────────────────────────
  http.get(`${API}/v1/entities`, () =>
    HttpResponse.json({
      data: {
        entities: Array.from({ length: 10 }, (_, i) => ({
          id: `user_${String(i + 1).padStart(4, '0')}`,
          kind: 'user',
          label: `User ${i + 1}`,
          email: `user${i + 1}@example.com`,
          trust_score: Math.round(65 + Math.random() * 30),
          created_at: new Date(Date.now() - (i + 1) * 7 * 86400_000).toISOString(),
        })),
        total: 10,
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/entities/search`, () =>
    HttpResponse.json({ data: { results: [], total: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/entities/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { id: params.entityId, kind: 'user', label: `User ${params.entityId}`, trust_score: 78 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Profile ───────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/profile/:userId/summary`, ({ params }) =>
    HttpResponse.json({
      data: {
        user_id: params.userId,
        name: `User ${String(params.userId).slice(-4)}`,
        email: `user@example.com`,
        trust_score: 78,
        risk_level: 'low',
        profile_completeness: 0.82,
        last_seen: new Date(Date.now() - 3600_000).toISOString(),
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId`, ({ params }) =>
    HttpResponse.json({
      data: {
        user_id: params.userId,
        name: `User ${String(params.userId).slice(-4)}`,
        email: `user@example.com`,
        trust_score: 78,
        risk_level: 'low',
        devices: [],
        sessions: [],
        timeline: [],
        intelligence: {},
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId/timeline`, ({ params }) =>
    HttpResponse.json({ user_id: params.userId, events: [], count: 0 }),
  ),
  http.get(`${API}/v1/profile/:userId/sessions`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, sessions: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/devices`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, devices: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/platforms`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, platforms: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/journeys`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, journeys: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/wallets`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, wallets: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/financials`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, accounts: [], total_balance_usd: 0, computed_at: new Date().toISOString() }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/rewards`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, campaigns: [], total_earned_usd: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/identifiers`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, identifiers: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/intelligence`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, signals: [], risk_level: 'low', trust_score: 78 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/relationships`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, relationships: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/provenance`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, sources: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/protocols`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, protocols: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/lake/:domain`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, domain: params.domain, records: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/social-intelligence`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.userId,
        kind: 'social_intelligence',
        window: '30d',
        items: [],
        summary: {
          total_followers_deduped: 0,
          influence_level: 'none',
          engagement_rate: 0,
          platforms_connected: 0,
        },
        provenance: { sources: [] },
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId/retarget-recommendations`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.userId,
        kind: 'retarget_recommendations',
        items: [],
        pagination: { limit: 20, count: 0, has_more: false },
        provenance: { sources: ['retarget_recommendations'] },
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/resolve`, () =>
    HttpResponse.json({ data: { resolved_user_id: 'user_0001' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Recommendations ───────────────────────────────────────────────────────────
  http.post(`${API}/v1/recommendations/:recommendationId/approve`, ({ params }) =>
    HttpResponse.json({ data: { recommendation_id: params.recommendationId, status: 'approved' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/recommendations/:recommendationId/reject`, ({ params }) =>
    HttpResponse.json({ data: { recommendation_id: params.recommendationId, status: 'rejected' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Geo ───────────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/geo/summary`, () =>
    HttpResponse.json({ data: null, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/geo/entities`, () =>
    HttpResponse.json({ data: null, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Campaigns ─────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/campaigns`, () =>
    HttpResponse.json({ data: { campaigns: [], total: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/campaigns/:campaignId`, ({ params }) =>
    HttpResponse.json({ data: { campaign_id: params.campaignId, name: 'Mock Campaign', status: 'draft' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/campaigns`, async ({ request }) => {
    const body = await request.json() as { name: string };
    return HttpResponse.json({ data: { campaign_id: `camp_${Date.now()}`, name: body.name, status: 'draft' }, status: 'ok', timestamp: new Date().toISOString() });
  }),

  // ── Behavioral / Expectations / Attribution ───────────────────────────────────
  http.get(`${API}/v1/behavioral/entity/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, signals: [] }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/expectations/entity/:entityId/explain`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.entityId,
        explanation: 'No anomalies detected.',
        signals: [],
        confidence: 0.9,
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/attribution/journey/:userId`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, touchpoints: [], journeys: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Graph ─────────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/entities/:entityId/graph`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, nodes: [], edges: [], node_count: 0, edge_count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/resolution/cluster/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, cluster_id: `cluster_${params.entityId}`, members: [], size: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/graph/traverse`, () =>
    HttpResponse.json({ data: { nodes: [], edges: [], node_count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Settings ──────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/me/settings`, () =>
    HttpResponse.json({ data: { notifications: true, theme: 'dark', timezone: 'UTC' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.patch(`${API}/v1/me/settings`, async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ data: body, status: 'ok', timestamp: new Date().toISOString() });
  }),

  // ── Auth refresh ──────────────────────────────────────────────────────────────
  http.post(`${API}/v1/auth/refresh`, () =>
    HttpResponse.json({ data: { access_token: 'mock_refreshed_token', expires_in: 3600 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/token`, () =>
    HttpResponse.json({ data: { access_token: 'mock_access_token', refresh_token: 'mock_refresh', expires_in: 3600 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Data Quality / Intelligence Quality (tenant-facing) ─────────────────────────
  http.get(`${API}/v1/data-quality/overview`, () =>
    HttpResponse.json({ data: {
      score: {
        tenant_id: 'tenant_demo_001', scope: 'tenant',
        event_quality_score: 0.96, schema_stability_score: 0.97, identity_resolution_score: 0.93,
        graph_quality_score: 0.94, profile_quality_score: 0.92, recommendation_quality_score: 0.9,
        outcome_feedback_quality_score: 0.91, playbook_quality_score: 0.9,
        overall_intelligence_quality_score: 0.929, status: 'healthy',
      },
      dimensions: {
        event_quality_score: { score: 0.96, status: 'healthy' },
        schema_stability_score: { score: 0.97, status: 'healthy' },
        identity_resolution_score: { score: 0.93, status: 'healthy' },
        graph_quality_score: { score: 0.94, status: 'healthy' },
        profile_quality_score: { score: 0.92, status: 'healthy' },
        recommendation_quality_score: { score: 0.9, status: 'healthy' },
        outcome_feedback_quality_score: { score: 0.91, status: 'healthy' },
        playbook_quality_score: { score: 0.9, status: 'healthy' },
      },
      open_drift_event_count: 0, drift_by_severity: {},
    }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/events`, () =>
    HttpResponse.json({ data: { dimension: 'event_quality_score', event_volume: 1000000, schema_validation_failure_rate: 0.004, duplicate_event_count: 210, late_arriving_event_count: 95, quality_score: 0.96, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/recommendations`, () =>
    HttpResponse.json({ data: { dimension: 'recommendation_quality_score', success_rate: 0.71, low_confidence_recommendation_rate: 0.11, suppression_rate: 0.09, quality_score: 0.9, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/graph`, () =>
    HttpResponse.json({ data: { dimension: 'graph_quality_score', orphaned_vertices: 73, dangling_edges: 12, missing_expected_edges: 41, quality_score: 0.94, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/:dimension`, ({ params }) =>
    HttpResponse.json({ data: { dimension: params.dimension, quality_score: 0.92, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Integrations / Connectors ───────────────────────────────────────────────
  http.get(`${API}/v1/integrations/connectors`, () =>
    HttpResponse.json({ data: { items: [
      { connector_type: 'slack', label: 'Slack', category: 'messaging', description: 'Ingest Slack activity.', premium: false, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'webhook', label: 'Generic Signed Webhook', category: 'webhook', description: 'Ingest events via HMAC-signed webhook.', premium: false, enabled: true, sync_status: 'healthy' },
      { connector_type: 'shopify', label: 'Shopify', category: 'commerce', description: 'Ingest orders and customers.', premium: false, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'stripe', label: 'Stripe (ingestion)', category: 'billing', description: 'Ingest payment events.', premium: false, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'hubspot', label: 'HubSpot', category: 'crm', description: 'Ingest contacts and deals.', premium: true, enabled: false, sync_status: 'never_synced' },
      { connector_type: 'segment', label: 'Segment', category: 'product_analytics', description: 'Ingest track/identify events.', premium: false, enabled: false, sync_status: 'never_synced' },
    ] }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
];
