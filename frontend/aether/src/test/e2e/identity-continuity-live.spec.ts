import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

const UI_BASE_URL = process.env.IDENTITY_STAGING_UI_BASE_URL;
const API_BASE_URL = process.env.AETHER_STAGING_BASE_URL;
const ADMIN_KEY = process.env.IDENTITY_STAGING_CAPTURE_API_KEY;

type Surface = 'activation' | 'review_queue';

async function installRunScopedAdminSession(page: Page): Promise<void> {
  if (!ADMIN_KEY) throw new Error('IDENTITY_STAGING_CAPTURE_API_KEY is required for live UI evidence');
  await page.addInitScript((key) => {
    sessionStorage.setItem('aether_session_key', key);
    sessionStorage.setItem('aether_session_expires_at', new Date(Date.now() + 30 * 60 * 1000).toISOString());
  }, ADMIN_KEY);
}

async function captureLiveEvidence(
  page: Page,
  testInfo: TestInfo,
  surface: Surface,
  identity: { deploymentId: string; tenantRef: string },
  observations: Array<{ method: string; path: string; status: number }>,
): Promise<void> {
  const outputDirectory = testInfo.outputPath('identity-ui-live-evidence');
  mkdirSync(outputDirectory, { recursive: true });
  const testId = testInfo.titlePath.join(' › ');
  const evidenceId = createHash('sha256')
    .update(`${identity.deploymentId}\0${identity.tenantRef}\0${surface}\0${testId}`)
    .digest('hex')
    .slice(0, 24);
  const screenshotName = `${evidenceId}-screenshot.png`;
  const structuredName = `${evidenceId}-observations.json`;
  const screenshotPath = testInfo.outputPath('identity-ui-live-evidence', screenshotName);
  const structuredPath = testInfo.outputPath('identity-ui-live-evidence', structuredName);
  const screenshot = await page.screenshot({ fullPage: true, animations: 'disabled' });
  const structured = {
    schema_version: 'aether.identity-ui-evidence.v2',
    evidence_class: 'ui_live_staging',
    api_mode: 'authenticated_real_backend',
    live_staging_claim: true,
    test_id: testId,
    surface,
    tenant_ref: identity.tenantRef,
    deployment_id: identity.deploymentId,
    captured_at: new Date().toISOString(),
    page_origin: new URL(UI_BASE_URL!).origin,
    api_origin: new URL(API_BASE_URL!).origin,
    page_path: new URL(page.url()).pathname,
    visible_headings: await page.getByRole('heading').allTextContents(),
    api_observations: observations,
    artifacts: { screenshot: screenshotName, structured: structuredName },
  };
  writeFileSync(screenshotPath, screenshot, { flag: 'wx' });
  writeFileSync(structuredPath, `${JSON.stringify(structured, null, 2)}\n`, { flag: 'wx' });
  writeFileSync(testInfo.outputPath('identity-ui-live-evidence', `${evidenceId}-manifest.json`), `${JSON.stringify({
    schema_version: 'aether.identity-ui-live-evidence-manifest.v1',
    id: evidenceId,
    evidence_class: 'ui_live_staging',
    api_mode: 'authenticated_real_backend',
    test_id: testId,
    surface,
    tenant_ref: identity.tenantRef,
    deployment_id: identity.deploymentId,
    captured_at: structured.captured_at,
    files: { screenshot: screenshotName, structured: structuredName },
  }, null, 2)}\n`, { flag: 'wx' });
  await testInfo.attach('identity-ui-live-screenshot', { body: screenshot, contentType: 'image/png' });
  await testInfo.attach('identity-ui-live-observations', {
    body: Buffer.from(`${JSON.stringify(structured, null, 2)}\n`),
    contentType: 'application/json',
  });
}

async function getStagingIdentity(page: Page): Promise<{ deploymentId: string; tenantRef: string }> {
  if (!API_BASE_URL || !ADMIN_KEY) {
    throw new Error('AETHER_STAGING_BASE_URL and IDENTITY_STAGING_CAPTURE_API_KEY are required for live UI evidence');
  }
  const response = await page.context().request.get(`${API_BASE_URL.replace(/\/$/, '')}/v1/admin/identity/staging-proof-capture`, {
    headers: { Authorization: `Bearer ${ADMIN_KEY}` },
  });
  if (!response.ok()) throw new Error(`staging identity capture returned HTTP ${response.status()}`);
  const envelope = await response.json() as { data?: { environment?: string; deployment_id?: string; capture?: { tenant_ref?: string } } };
  const data = envelope.data;
  if (data?.environment !== 'staging' || !data.deployment_id || !data.capture?.tenant_ref) {
    throw new Error('staging capture omitted its environment, deployment, or tenant binding');
  }
  return { deploymentId: data.deployment_id, tenantRef: data.capture.tenant_ref };
}

async function authenticatedSurface(page: Page, testInfo: TestInfo, surface: Surface): Promise<void> {
  test.skip(!UI_BASE_URL || !API_BASE_URL || !ADMIN_KEY, 'live staging UI credentials and origins are not configured');
  await installRunScopedAdminSession(page);
  const observations: Array<{ method: string; path: string; status: number }> = [];
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/v1/')) {
      observations.push({ method: response.request().method(), path: url.pathname, status: response.status() });
    }
  });
  const identity = await getStagingIdentity(page);
  await page.goto(surface === 'activation' ? '/identity/activation' : '/identity/reviews');
  if (surface === 'activation') {
    await expect(page.getByRole('heading', { name: 'Activation Status' })).toBeVisible();
    await expect(page.getByText('Loading activation status...')).toHaveCount(0);
  } else {
    await expect(page.getByRole('heading', { name: 'Review Queue' })).toBeVisible();
    await expect(page.getByText('Loading review queue...')).toHaveCount(0);
  }
  const expected = surface === 'activation'
    ? ['/v1/me', '/v1/capabilities', '/v1/admin/identity/activation-status']
    : ['/v1/me', '/v1/capabilities', '/v1/admin/identity/review-queue'];
  for (const path of expected) {
    expect(observations.some((item) => item.path === path && item.status >= 200 && item.status < 300), `live request ${path} must succeed`).toBe(true);
  }
  await captureLiveEvidence(page, testInfo, surface, identity, observations);
}

test('live staging activation dashboard uses authenticated tenant capabilities and status', async ({ page }, testInfo) => {
  await authenticatedSurface(page, testInfo, 'activation');
});

test('live staging identity review queue loads through authenticated tenant scope', async ({ page }, testInfo) => {
  await authenticatedSurface(page, testInfo, 'review_queue');
});
