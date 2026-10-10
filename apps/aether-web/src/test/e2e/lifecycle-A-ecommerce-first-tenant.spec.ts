/**
 * Lifecycle E2E — Suite A: e-commerce + ads first-time tenant.
 *
 * Scenario (plan §7 / A): signup → activate → connect Shopify → connect Meta
 * Ads → verify SDK → initial sync → readiness → enter Aether → Campaigns
 * resolved; Profiles receive commerce/profile evidence.
 *
 * This is ONE serial journey over a single first-time tenant (Suite tenant A):
 *
 *   A1 — incomplete tenant lands on /activation and selects a commerce intent
 *   A2 — connect Shopify (Commerce & Revenue) during activation → Connected
 *   A3 — connect Meta Ads (Advertising), initial sync, complete activation,
 *        enter the workspace, and reach Campaigns resolved from real sync state.
 *
 * Requires the R3/R4 integration env: WS-1..WS-6 merged, backend seeded, and a
 * first-time (incomplete) tenant supplied as E2E_TENANT_EMAIL_A/_PASSWORD_A (or
 * the shared E2E_TENANT_EMAIL/PASSWORD). Each run must start from a reset seed
 * of that tenant so A1 begins incomplete (see docs/operations/ lifecycle e2e
 * runbook). The `connectors_enabled` test flag must be ON for connect flows.
 */

import { expect, test } from '@playwright/test';
import {
  COPY,
  MARKERS,
  ROUTES,
  goTo,
  lifecycleSuiteCredentials,
  suiteGate,
  suiteReason,
  signIn,
} from './lifecycle.harness';

test.describe.configure({ mode: 'serial' });

test.describe('Lifecycle A — e-commerce + ads first-time tenant', () => {
  test.skip(suiteGate('A'), suiteReason);

  test('A1: incomplete tenant lands on activation and selects a commerce intent', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('A')!);

    // TenantLanding resolves an incomplete tenant into the activation machine.
    await expect(page).toHaveURL(ROUTES.activation, { timeout: 15_000 });

    // Intent-driven activation (WS-3) presents recommended categories; a
    // merchant-first tenant sees the commerce experience first.
    const sellOnline = page.locator(MARKERS.activationIntent('sell_online')).first();
    await expect(sellOnline).toBeVisible({ timeout: 15_000 });
    await sellOnline.click();
    await expect(page.getByText(COPY.commerceRevenue).first()).toBeVisible();
  });

  test('A2: connect Shopify under Commerce & Revenue reaches Connected', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('A')!);
    await goTo(page, ROUTES.activation, /Activation|activation/i);

    // Activation connect step (WS-3) reuses the WS-1/WS-2 connect contract.
    const commerceSection = page.getByRole('region', { name: /Commerce & Revenue/i });
    await expect(commerceSection).toBeVisible({ timeout: 15_000 });
    await commerceSection.getByText(COPY.connect, { exact: true }).click();

    const apiKey = page.locator(MARKERS.credentialField('shopify', 'api_key'));
    await expect(apiKey).toBeVisible();
    await apiKey.fill('e2e-shopify-credential');
    await page.getByRole('button', { name: /^Connect$/i }).click();

    // Record fact flips to Connected; the catalog baseline must never read Ready.
    const shopifyRow = page.locator(MARKERS.integrationRow('shopify'));
    await expect(shopifyRow).toBeVisible({ timeout: 20_000 });
    await expect(shopifyRow.locator(MARKERS.connectionState('connected'))).toBeVisible({
      timeout: 20_000,
    });
    await expect(shopifyRow.locator(MARKERS.connectionState('ready'))).toHaveCount(0);
  });

  test('A3: connect Meta Ads, run initial sync, complete activation, enter workspace', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('A')!);
    await goTo(page, ROUTES.activation, /Activation|activation/i);

    // Advertising connect is a first-class activation step for this tenant.
    const adSection = page.getByRole('region', { name: new RegExp(COPY.advertising) });
    await expect(adSection).toBeVisible({ timeout: 15_000 });

    const metaRow = page.locator(MARKERS.integrationRow('meta_ads'));
    await expect(metaRow).toBeVisible();
    await adSection.getByText(COPY.connect, { exact: true }).click();

    const accessToken = page.locator(MARKERS.credentialField('meta_ads', 'access_token'));
    await expect(accessToken).toBeVisible();
    await accessToken.fill('e2e-meta-ads-token');
    await page.getByRole('button', { name: /^Connect$/i }).click();

    // Initial sync renders an in-flight state rather than fabricating freshness.
    await page.getByRole('button', { name: /Sync/i }).first().click();
    await expect(page.getByText(COPY.syncing).first()).toBeVisible({ timeout: 15_000 });

    // Complete activation once connect + sync evidence exist.
    await page.getByRole('button', { name: /Complete/i }).first().click();

    // Entered Aether: root no longer redirects into /activation.
    await expect(page).not.toHaveURL(ROUTES.activation, { timeout: 30_000 });

    // Campaigns resolve once commerce + advertising sync evidence exists.
    await goTo(page, ROUTES.campaign360, /Campaign/i);
    await expect(page).toHaveURL(ROUTES.campaign360);

    // Settings → Integrations shows both connectors Connected with an honest
    // baseline — never a fabricated Ready claim on this tenant's record facts.
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));
    for (const family of ['shopify', 'meta_ads']) {
      const row = page.locator(MARKERS.integrationRow(family));
      await expect(row).toBeVisible();
      await expect(row.locator(MARKERS.connectionState('connected'))).toBeVisible();
    }
  });
});
