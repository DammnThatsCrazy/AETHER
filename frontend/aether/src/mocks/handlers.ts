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
  http.post(`${API}/v1/auth/otp/request`, () =>
    HttpResponse.json({ data: { message: 'Code sent' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/otp/verify`, () =>
    HttpResponse.json({ data: { api_key: 'ak_mock_dev_key_from_otp_verify', tenant_id: 'tenant_demo_001', message: 'Verified' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/register`, () =>
    HttpResponse.json({ data: { message: 'Check your email', email: 'user@example.com' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/login`, () =>
    HttpResponse.json({ data: { api_key: 'ak_mock_login_key', tenant_id: 'tenant_demo_001' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
];
