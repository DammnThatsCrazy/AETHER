import { mkdirSync, writeFileSync } from 'node:fs';
import { basename } from 'node:path';
import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test';

const TENANT_A = 'tenant_identity_e2e_a';
const TENANT_B = 'tenant_identity_e2e_b';
const ENVELOPE = (data: unknown) => ({
  data,
  status: 'success',
  timestamp: '2026-09-27T12:00:00.000Z',
});

type UiEvidenceMetadata = {
  surface: 'activation' | 'review_queue' | 'profile_360';
  tenantRef: string;
  observations?: Array<{ method: string; path: string; authorization: string | null }>;
};

/** Persist raw UI evidence while marking fixture-backed API traffic as non-staging evidence. */
async function captureUiEvidence(page: Page, testInfo: TestInfo, metadata: UiEvidenceMetadata): Promise<void> {
  const outputDirectory = testInfo.outputPath('identity-ui-evidence');
  mkdirSync(outputDirectory, { recursive: true });
  const testId = testInfo.titlePath.join(' › ');
  const artifactStem = `${metadata.surface}-${metadata.tenantRef}`;
  const screenshotPath = testInfo.outputPath('identity-ui-evidence', `${artifactStem}-screenshot.png`);
  const structuredPath = testInfo.outputPath('identity-ui-evidence', `${artifactStem}-observations.json`);
  const screenshot = await page.screenshot({ fullPage: true, animations: 'disabled' });
  const structure = {
    schema_version: 'aether.identity-ui-evidence.v1',
    evidence_class: 'ui_fixture_only',
    api_mode: 'playwright_route_fixture',
    live_staging_claim: false,
    test_id: testId,
    surface: metadata.surface,
    tenant_ref: metadata.tenantRef,
    captured_at: new Date().toISOString(),
    page_url: new URL(page.url()).pathname + new URL(page.url()).search,
    visible_headings: await page.getByRole('heading').allTextContents(),
    visible_page_text: (await page.locator('body').innerText()).slice(0, 12000),
    api_observations: metadata.observations ?? [],
    artifacts: {
      screenshot: basename(screenshotPath),
      structured: basename(structuredPath),
    },
  };
  writeFileSync(screenshotPath, screenshot, { flag: 'wx' });
  writeFileSync(structuredPath, `${JSON.stringify(structure, null, 2)}\n`, { flag: 'wx' });
  const manifestPath = testInfo.outputPath('identity-ui-evidence', `${artifactStem}-manifest.json`);
  writeFileSync(manifestPath, `${JSON.stringify({
    schema_version: 'aether.identity-ui-evidence-manifest.v1',
    evidence_class: 'ui_fixture_only',
    api_mode: 'playwright_route_fixture',
    test_id: testId,
    surface: metadata.surface,
    tenant_ref: metadata.tenantRef,
    captured_at: structure.captured_at,
    files: { screenshot: basename(screenshotPath), structured: basename(structuredPath) },
  }, null, 2)}\n`, { flag: 'wx' });
  await testInfo.attach('identity-ui-screenshot', { body: screenshot, contentType: 'image/png' });
  await testInfo.attach('identity-ui-observations', { body: Buffer.from(`${JSON.stringify(structure, null, 2)}\n`), contentType: 'application/json' });
}

function activationStatus(tenantId: string) {
  return {
    tenant_id: tenantId,
    historical_data_status: 'available',
    sdk_status: 'stale',
    resolution_counts: {
      total_entities: 14,
      total_aliases: 22,
      total_clusters: 3,
      recent_merges: 2,
      recent_splits: 1,
    },
    conflict_counts: { open: 2, resolved: 4, dismissed: 1 },
    projection_restatement_status: 'needs_attention',
    projection_restatement_counts: { failed: 1, queued: 2, running: 1 },
    pending_review_counts: {
      open: 2,
      approving: 0,
      approval_recovery_required: 1,
      merge_committed: 0,
    },
    runtime_flags: {
      identity_resolution_enabled: true,
      projection_restatement_enabled: false,
    },
    sdk_last_seen_at: '2026-09-26T12:00:00.000Z',
    computed_at: '2026-09-27T12:00:00.000Z',
  };
}

function capabilityFixture(tenantId: string) {
  return {
    tenant_id: tenantId,
    release: {
      deployment_profile: 'test', environment: 'test', release_class: null,
      enforcement: { policy_enforcement: true, route_registry_enforced: true, kyber_operator_gate: true },
      enabled_route_prefixes: ['/v1/identity', '/v1/admin/identity'], excluded_domains: [],
    },
    profile_sub_resources: [], providers: [], consent_purposes_granted: [], consent_purposes_all: [],
    feature_flags: {
      tenant_identity_activation_dashboard_enabled: true,
      identity_explainability_enabled: true,
      identity_manual_review_enabled: true,
    },
    evaluated_at: '2026-09-27T12:00:00.000Z',
  };
}

function reviewEntry(tenantId: string, status = 'open') {
  return {
    conflict_id: `review-${tenantId}-1234`,
    tenant_id: tenantId,
    entry_type: 'late_binding_candidate',
    candidate_a: { entity_id: '' },
    candidate_b: { entity_id: '' },
    candidate_source_identity_ids: [`csv-import-${tenantId}`],
    identify_source_identity_id: `sdk-source-${tenantId}`,
    reason_codes: ['durable_consent_required', 'provisional_import_target'],
    authority: 'tenant_review_required',
    seen_count: 2,
    matching_evidence: [
      {
        source_identity_id: `csv-import-${tenantId}`,
        provisional_canonical_entity_id: `profile-${tenantId}-001`,
        claim_type: 'email',
        claim_verification_status: 'verified',
      },
    ],
    conflicting_evidence: [{ type: 'consent', status: 'missing' }],
    recommended_action: 'review_identity_evidence',
    confidence: 0.72,
    risk_level: 'medium',
    affected_projections: ['profile_360', 'journey'],
    created_at: '2026-09-27T11:00:00.000Z',
    status,
  };
}

interface ApiFixtureOptions {
  tenantId: string;
  accessToken?: string;
  reviewStatus?: string;
  onRequest?: (request: { method: string; path: string; body: unknown; authorization: string | null }) => void;
}

/**
 * Test-only backend fixture at the actual /v1 routes consumed by api.identity.
 * This exercises the production REST client, auth restoration, and components;
 * it does not claim a live backend integration test.
 */
async function stubIdentityApi(page: Page, options: ApiFixtureOptions): Promise<void> {
  const accessToken = options.accessToken ?? `session-${options.tenantId}`;
  await page.addInitScript((token) => {
    const expiresAt = new Date(Date.now() + 60 * 60 * 1000).toISOString();
    sessionStorage.setItem('aether_session_token', token);
    sessionStorage.setItem('aether_session_expires_at', expiresAt);
    sessionStorage.setItem('aether_session_key', token);
  }, accessToken);

  let currentReview = reviewEntry(options.tenantId, options.reviewStatus ?? 'open');
  let queueIsEmpty = false;

  await page.route('**/v1/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() as unknown;
    options.onRequest?.({
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      body,
      authorization: request.headers()['authorization'] ?? null,
    });

    const fulfill = (data: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(ENVELOPE(data)),
    });

    if (request.method() === 'GET' && url.pathname === '/v1/me') {
      return fulfill({
        tenant_id: options.tenantId,
        name: `Identity E2E ${options.tenantId}`,
        contact_email: `${options.tenantId}@example.test`,
        plan: { plan_id: 'e2e-plan', display_name: 'E2E', monthly_quota: 1000, burst_rpm: 100 },
        billing: {},
        api_key_count: 0,
        is_admin: true,
        graph_scope: {
          tenant_id: options.tenantId,
          workspace_id: `workspace-${options.tenantId}`,
          environment_id: 'test',
          scope_model: 'single_workspace_tenant_v1',
        },
      });
    }
    if (request.method() === 'GET' && url.pathname === '/v1/capabilities') {
      return fulfill(capabilityFixture(options.tenantId));
    }
    if (request.method() === 'GET' && url.pathname === '/v1/identity/activation-status') {
      if (url.searchParams.has('tenant_id')) return fulfill({ detail: 'Tenant must come from auth' }, 403);
      return fulfill(activationStatus(options.tenantId));
    }
    if (request.method() === 'GET' && url.pathname === '/v1/identity/review-queue') {
      return fulfill({
        entries: queueIsEmpty ? [] : [currentReview],
        total: queueIsEmpty ? 0 : 1,
        status: 'ok',
      });
    }
    const approvePath = new RegExp(`^/v1/identity/review-queue/${currentReview.conflict_id}/approve$`);
    if (request.method() === 'POST' && approvePath.test(url.pathname)) {
      if ((body as { tenant_id?: string } | null)?.tenant_id) return fulfill({ detail: 'Tenant must come from auth' }, 403);
      currentReview = { ...currentReview, status: 'approved' };
      queueIsEmpty = true;
      return fulfill({ status: 'approved', reason_codes: [] });
    }
    if (request.method() === 'POST' && url.pathname.includes('/reject')) {
      return fulfill({ status: 'rejected', reason_codes: ['tenant_review_rejected'] });
    }

    return fulfill({ detail: 'No identity E2E fixture for this route' }, 500);
  });
}

test('activation status renders tenant-backed fixture states, counts, and runtime flags', async ({ page }, testInfo) => {
  const requests: Array<{ method: string; path: string; body: unknown; authorization: string | null }> = [];
  await stubIdentityApi(page, { tenantId: TENANT_A, onRequest: (request) => requests.push(request) });
  await page.goto('/identity-continuity.e2e.html?surface=activation');

  await expect(page.getByRole('heading', { name: 'Activation Status' })).toBeVisible();
  await expect(page.getByText(TENANT_A)).toBeVisible();
  await expect(page.getByText('available', { exact: true })).toBeVisible();
  await expect(page.getByText('stale', { exact: true })).toBeVisible();
  await expect(page.getByText(/no heartbeat arrived in the last 24 hours/i)).toBeVisible();
  await expect(page.getByText('needs_attention', { exact: true })).toBeVisible();
  await expect(page.getByText('14', { exact: true })).toBeVisible();
  await expect(page.getByText('22', { exact: true })).toBeVisible();
  await expect(page.getByText('Open Identity Reviews')).toBeVisible();
  await expect(page.getByText('Failed Restatements')).toBeVisible();
  await expect(page.getByText('Pending Restatements')).toBeVisible();
  await expect(page.getByText('identity resolution enabled')).toBeVisible();
  await expect(page.getByText('projection restatement enabled')).toBeVisible();
  await expect(page.getByText('disabled', { exact: true })).toBeVisible();

  const statusRequest = requests.find((request) => request.path.startsWith('/v1/identity/activation-status'));
  expect(statusRequest).toMatchObject({
    method: 'GET',
    path: '/v1/identity/activation-status',
    authorization: `Bearer session-${TENANT_A}`,
  });
  await captureUiEvidence(page, testInfo, {
    surface: 'activation', tenantRef: TENANT_A,
    observations: requests.map(({ method, path, authorization }) => ({ method, path, authorization: authorization ? 'fixture-session-present' : null })),
  });
});

test('review queue shows pending candidate, evidence reasons, and an approved server result', async ({ page }, testInfo) => {
  const requests: Array<{ method: string; path: string; body: unknown; authorization: string | null }> = [];
  await stubIdentityApi(page, { tenantId: TENANT_A, onRequest: (request) => requests.push(request) });
  await page.goto('/identity-continuity.e2e.html?surface=review-queue');

  await expect(page.getByText('1 open identity review')).toBeVisible();
  await expect(page.getByText('Identity candidate', { exact: false })).toBeVisible();
  await expect(page.getByText('csv-import-tenant_identity_e2e_a')).toBeVisible();
  await expect(page.getByText('profile-tenant_identity_e2e_a-001')).toBeVisible();
  await expect(page.getByText(/durable_consent_required, provisional_import_target/)).toBeVisible();
  await expect(page.getByText(/approval asks the server to recheck current import evidence/i)).toBeVisible();

  await page.getByRole('button', { name: 'Approve after server checks' }).click();
  await expect(page.getByRole('status')).toContainText('Latest late-binding action');
  await expect(page.getByRole('status')).toContainText('approved');
  await expect(page.getByText('No open identity reviews')).toBeVisible();

  const approveRequest = requests.find((request) => request.method === 'POST' && request.path.endsWith('/approve'));
  expect(approveRequest).toMatchObject({
    path: `/v1/identity/review-queue/review-${TENANT_A}-1234/approve`,
    body: {},
    authorization: `Bearer session-${TENANT_A}`,
  });
  await captureUiEvidence(page, testInfo, {
    surface: 'review_queue', tenantRef: TENANT_A,
    observations: requests.map(({ method, path, authorization }) => ({ method, path, authorization: authorization ? 'fixture-session-present' : null })),
  });
});

test('review queue binds results to each authenticated tenant fixture', async ({ browser }, testInfo) => {
  const tenantPages = await Promise.all([TENANT_A, TENANT_B].map(async (tenantId) => {
    const context = await browser.newContext({ baseURL: 'http://localhost:5175' });
    const page = await context.newPage();
    await stubIdentityApi(page, { tenantId });
    await page.goto('/identity-continuity.e2e.html?surface=review-queue');
    await expect(page.getByText(`csv-import-${tenantId}`)).toBeVisible();
    await expect(page.getByText(`profile-${tenantId}-001`)).toBeVisible();
    return { context, page, tenantId };
  }));

  for (const { context, page, tenantId } of tenantPages) {
    await expect(page.getByText(`csv-import-${tenantId === TENANT_A ? TENANT_B : TENANT_A}`)).toHaveCount(0);
    await captureUiEvidence(page, testInfo, { surface: 'review_queue', tenantRef: tenantId });
    await context.close();
  }
});

test('recovery-required candidate is visibly pending safe server recovery', async ({ page }, testInfo) => {
  await stubIdentityApi(page, { tenantId: TENANT_A, reviewStatus: 'approval_recovery_required' });
  await page.goto('/identity-continuity.e2e.html?surface=review-queue');

  await expect(page.getByRole('status')).toContainText('approval outcome needs recovery');
  await expect(page.getByRole('button', { name: 'Retry server recovery' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Reject without linking' })).toHaveCount(0);
  await expect(page.getByText(/durable_consent_required/)).toBeVisible();
  await captureUiEvidence(page, testInfo, { surface: 'review_queue', tenantRef: TENANT_A });
});

test('Profile 360 explains source evidence, ignored evidence, and current graph version', async ({ page }, testInfo) => {
  const requests: Array<{ method: string; path: string; authorization: string | null }> = [];
  const tenantId = TENANT_A;
  await page.addInitScript((token) => {
    sessionStorage.setItem('aether_session_token', token);
    sessionStorage.setItem('aether_session_expires_at', new Date(Date.now() + 60 * 60 * 1000).toISOString());
    sessionStorage.setItem('aether_session_key', token);
  }, `session-${tenantId}`);
  await page.route('**/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path, authorization: request.headers()['authorization'] ?? null });
    const data = path === '/v1/capabilities'
      ? capabilityFixture(tenantId)
      : path === '/v1/me'
      ? {
          tenant_id: tenantId,
          name: 'Profile identity E2E',
          contact_email: `${tenantId}@example.test`,
          plan: { plan_id: 'e2e-plan', display_name: 'E2E', monthly_quota: 1000, burst_rpm: 100 },
          billing: {},
          api_key_count: 0,
          is_admin: true,
          graph_scope: { tenant_id: tenantId, workspace_id: 'workspace-a', environment_id: 'test', scope_model: 'single_workspace_tenant_v1' },
        }
      : path === '/v1/identity/profiles/profile-import-sdk-late-binding'
        ? { id: 'profile-import-sdk-late-binding', tenant_id: tenantId }
        : path === '/v1/identity/profiles/profile-import-sdk-late-binding/identity/explanation'
          ? {
              canonical_entity_id: 'profile-import-sdk-late-binding',
              confidence: 0.94,
              confidence_band: 'high',
              source_identities: [{
                source_identity_id: 'source-csv-17',
                source: 'CSV import',
                source_platform: 'csv',
                source_event_id: 'import-commit-17',
                alias_type: 'email_hash',
                confidence: 0.94,
                first_seen_at: '2026-09-01T10:00:00Z',
                last_seen_at: '2026-09-27T10:00:00Z',
                alias_display_value_redacted: 'j***@example.test',
              }],
              positive_evidence: [{ signal: 'verified_email', status: 'accepted', reason_codes: ['same_verified_email'], source_events: ['sdk-identify-17'], source_connectors: ['csv'], decision_type: 'auto_resolve' }],
              negative_evidence: [],
              ignored_evidence: [{ signal: 'device_fingerprint', status: 'ignored', reason_codes: ['fingerprint_not_merge_authority'], source_events: ['sdk-page-view-18'], source_connectors: [], decision_type: 'review_required' }],
              graph_version: 'v12',
              resolution_decision_summary: 'The SDK identity was linked to the imported profile using consented verified email evidence. A device fingerprint was ignored for merge authority.',
            }
          : { detail: 'No profile identity fixture for this route' };
    return route.fulfill({
      status: path.startsWith('/v1/identity/profiles/') ? 200 : 200,
      contentType: 'application/json',
      body: JSON.stringify(ENVELOPE(data)),
    });
  });

  await page.goto('/identity-continuity.e2e.html?surface=profile');

  await expect(page.getByText('profile-import-sdk-late-binding', { exact: true })).toBeVisible();
  await expect(page.getByText('High', { exact: true })).toBeVisible();
  await expect(page.getByText('CSV import')).toBeVisible();
  await expect(page.getByText('j***@example.test')).toBeVisible();
  await expect(page.getByText('Graph version: v12')).toBeVisible();
  await expect(page.getByText('Reason: fingerprint not merge authority')).toBeVisible();
  await expect(page.getByText(/device fingerprint was ignored for merge authority/i)).toBeVisible();

  expect(requests).toContainEqual({
    method: 'GET',
    path: '/v1/identity/profiles/profile-import-sdk-late-binding/identity/explanation',
    authorization: `Bearer session-${tenantId}`,
  });
  await captureUiEvidence(page, testInfo, {
    surface: 'profile_360', tenantRef: tenantId,
    observations: requests.map(({ method, path, authorization }) => ({ method, path, authorization: authorization ? 'fixture-session-present' : null })),
  });
});
