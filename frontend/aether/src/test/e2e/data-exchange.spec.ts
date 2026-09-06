import { test, expect, type Page } from '@playwright/test';

/**
 * M6 Data Exchange — Settings surface E2E (route-state-matrix evidence).
 *
 * The app shell talks to a dead backend (VITE_API_BASE_URL=http://localhost:8000
 * in the Playwright webServer), so every /v1 request is mocked at the network
 * seam. The Data Exchange Settings section is gated in two layers, mirroring
 * production: the section only MOUNTS when the canonical tenant capability
 * contract (GET /v1/capabilities → feature_flags.data_exchange_enabled) says
 * the plane is on, and once mounted its import/export/report surface is driven
 * by the *data-exchange* capability contract
 * (GET /v1/data-exchange/capabilities).
 *
 * Scenarios:
 *   enabled  → capability summary + artifact history render from mocked /v1/data-exchange/*
 *   disabled → "Data Exchange is not enabled for this workspace" EmptyState
 */

const ENVELOPE = (data: unknown) => ({
  data,
  status: 'success',
  timestamp: '2026-09-05T00:00:00.000Z',
});

const ME_PROFILE = {
  tenant_id: 't_e2e_001',
  name: 'E2E Tenant',
  contact_email: 'e2e@acme.io',
  plan: { plan_id: 'p_e2e', display_name: 'Demo', monthly_quota: 1000, burst_rpm: 100 },
  billing: {},
};

/** Full tenant capability contract (validated by `src/lib/api/capabilities.ts`). */
const TENANT_CAPABILITIES = {
  tenant_id: 't_e2e_001',
  release: {
    deployment_profile: 'demo',
    environment: 'test',
    release_class: 'preview',
    enforcement: {
      policy_enforcement: true,
      route_registry_enforced: true,
      kyber_operator_gate: false,
    },
    enabled_route_prefixes: [],
    excluded_domains: [],
  },
  profile_sub_resources: [],
  providers: [],
  consent_purposes_granted: [],
  consent_purposes_all: [],
  // The Data Exchange Settings section is gated on the canonical contract
  // (feature_flags.data_exchange_enabled) — mirroring the plane setting that
  // mounts /v1/data-exchange/*. Per-scenario the flag is overridden in
  // mockAuthenticatedBackend so it stays aligned with the DX-capabilities body.
  feature_flags: {
    data_quality_enabled: true,
    connectors_enabled: true,
    data_exchange_enabled: false,
  },
  evaluated_at: '2026-09-05T00:00:00.000Z',
};

function dataExchangeCapabilities(enabled: boolean) {
  return {
    data_exchange: {
      enabled,
      flags: enabled
        ? {
            imports_enabled: true,
            exports_enabled: true,
            reports_enabled: true,
            object_store_enabled: true,
          }
        : {},
    },
    available_formats: ['csv', 'json', 'ndjson', 'parquet', 'pdf'],
    available_sources: ['file', 's3'],
    blocked_classifications: ['secret', 'credential'],
  };
}

const ARTIFACTS = {
  artifacts: [
    {
      artifact_id: 'art_import_1',
      tenant_id: 't_e2e_001',
      direction: 'ingress',
      artifact_type: 'import_source',
      filename: 'customers.csv',
      format: 'csv',
      content_type: 'text/csv',
      size_bytes: 184320,
      classification: 'identifier',
      status: 'committed',
      created_at: '2026-07-30T12:00:00.000Z',
    },
    {
      artifact_id: 'art_export_1',
      tenant_id: 't_e2e_001',
      direction: 'egress',
      artifact_type: 'export',
      filename: 'customers_export.ndjson',
      format: 'ndjson',
      content_type: 'application/x-ndjson',
      size_bytes: 4096,
      classification: 'pii',
      status: 'available',
      created_at: '2026-08-01T00:00:00.000Z',
    },
  ],
  count: 2,
};

/**
 * Authenticate as a session-token holder and stub every /v1 call so the dead
 * backend is never reached. The session token must be accompanied by a future
 * expiry (AuthProvider restores + verifies against GET /v1/me); the legacy
 * session key is also seeded so the AppShell re-auth banner stays hidden.
 */
async function mockAuthenticatedBackend(page: Page, dataExchangeEnabled: boolean): Promise<void> {
  await page.addInitScript(() => {
    const token = 'e2e-session-token';
    const expiresAt = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    sessionStorage.setItem('aether_session_token', token);
    sessionStorage.setItem('aether_session_expires_at', expiresAt);
    sessionStorage.setItem('aether_session_key', token);
  });

  await page.route('**/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();

    const fulfill = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });

    if (method === 'GET' && path === '/v1/me') {
      return fulfill(ENVELOPE(ME_PROFILE));
    }
    if (method === 'GET' && path === '/v1/capabilities') {
      return fulfill(
        ENVELOPE({
          ...TENANT_CAPABILITIES,
          feature_flags: {
            ...TENANT_CAPABILITIES.feature_flags,
            data_exchange_enabled: dataExchangeEnabled,
          },
        }),
      );
    }
    if (method === 'GET' && path === '/v1/data-exchange/capabilities') {
      return fulfill(ENVELOPE(dataExchangeCapabilities(dataExchangeEnabled)));
    }
    if (method === 'GET' && path === '/v1/data-exchange/artifacts') {
      return fulfill(ENVELOPE(ARTIFACTS));
    }
    // Everything else (api keys, webhooks, notifications, demo-seed, ...) is an
    // explicit mock-unavailable so those Settings sections render error states
    // fast instead of waiting on the dead backend.
    return fulfill({ error: 'e2e mock unavailable', code: 'E2E_MOCK_UNAVAILABLE' }, 500);
  });
}

test('Data Exchange settings: capability summary + artifact history render when enabled', async ({
  page,
}) => {
  await mockAuthenticatedBackend(page, true);
  await page.goto('/settings/data-exchange');

  const section = page.getByTestId('data-exchange-section');
  await expect(section).toBeVisible({ timeout: 30_000 });

  // Capability surface summary from GET /v1/data-exchange/capabilities.
  await expect(section.getByText('Import engine')).toBeVisible();
  await expect(section.getByText('Exports')).toBeVisible();
  await expect(section.getByText('Reports')).toBeVisible();
  await expect(section.getByText('Signed transfers')).toBeVisible();

  // Artifact history from GET /v1/data-exchange/artifacts.
  await expect(section.getByText('customers.csv')).toBeVisible();
  await expect(section.getByText('customers_export.ndjson')).toBeVisible();
  await expect(section.getByText('Artifact history · 2')).toBeVisible();

  // Creation affordances are present when the surface is enabled.
  await expect(section.getByRole('button', { name: 'New export' })).toBeEnabled();
  await expect(section.getByRole('button', { name: 'New report' })).toBeEnabled();
});

test('Data Exchange settings: not-enabled EmptyState renders when the capability is off', async ({
  page,
}) => {
  await mockAuthenticatedBackend(page, false);
  await page.goto('/settings/data-exchange');

  const section = page.getByTestId('data-exchange-section');
  await expect(section).toBeVisible({ timeout: 30_000 });

  await expect(
    section.getByText('Data Exchange is not enabled for this workspace'),
  ).toBeVisible();

  // Creation affordances are hidden, not merely disabled, when the whole
  // data-exchange capability is off.
  await expect(section.getByRole('button', { name: 'New export' })).not.toBeAttached();
  await expect(section.getByRole('button', { name: 'New report' })).not.toBeAttached();
});
