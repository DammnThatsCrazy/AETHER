/**
 * Lifecycle E2E — Suite B: returning expansion tenant.
 *
 * Scenario (plan §7 / B): Campaign 360 → contextual add advertising →
 * Settings/Integrations → connect Google Ads → select account → sync → return.
 *
 * Serial journey over Suite tenant B (an activated tenant with commerce already
 * connected so Campaign 360 has data). Requires WS-1/WS-2/WS-4 surfaces plus a
 * reset seed of the tenant before each run (see docs/operations/ e2e runbook).
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

test.describe('Lifecycle B — returning expansion (add advertising)', () => {
  test.skip(suiteGate('B'), suiteReason);

  test('B1: Campaign 360 offers a contextual advertising add that routes into Integrations', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('B')!);

    // Returning tenant enters the workspace root (activation already complete).
    await expect(page).not.toHaveURL(ROUTES.activation, { timeout: 15_000 });

    // Campaign 360 (commerce data present) surfaces a contextual add path for
    // advertising — the empty-state CTA carries the ?return= handoff (WS-4).
    await goTo(page, ROUTES.campaign360, /Campaign/i);
    const addAds = page.getByRole('button', { name: /Add advertising/i }).first();
    await expect(addAds).toBeVisible({ timeout: 15_000 });
    await addAds.click();

    // Contextual add lands in Settings → Integrations, advertising section,
    // and remembers where to return.
    await expect(page).toHaveURL(new RegExp(ROUTES.settingsIntegrations), { timeout: 15_000 });
    const adSection = page.getByRole('region', { name: new RegExp(COPY.advertising) });
    await expect(adSection).toBeVisible();

    const googleRow = page.locator(MARKERS.integrationRow('google_ads'));
    await expect(googleRow).toBeVisible();
  });

  test('B2: connect Google Ads with account selection, sync, and return to Campaigns', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('B')!);
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));

    // Connect Google Ads from the advertising section.
    const adSection = page.getByRole('region', { name: new RegExp(COPY.advertising) });
    const googleRow = adSection.locator(MARKERS.integrationRow('google_ads'));
    await googleRow.getByText(COPY.connect, { exact: true }).click();

    // Credential grant → account discovery/selection (WS-2 multi-account).
    const customerId = page.locator(MARKERS.credentialField('google_ads', 'customer_id'));
    await expect(customerId).toBeVisible({ timeout: 15_000 });
    await customerId.fill('e2e-customer-000-000-0000');
    await page.getByRole('button', { name: /^Connect$/i }).click();

    // Multi-account model: an account picker appears once credentials resolve.
    const accountPicker = page.locator('[data-account-picker]');
    await expect(accountPicker).toBeVisible({ timeout: 20_000 });
    await accountPicker.locator('input[type="radio"]').first().check();

    await page.getByRole('button', { name: /Continue|Select account/i }).click();

    // Sync the selected account, then return to the originating surface.
    await page.getByRole('button', { name: /Sync/i }).first().click();
    await expect(page.getByText(COPY.syncing).first()).toBeVisible({ timeout: 15_000 });
    const returnBtn = page.getByRole('button', { name: /Return to Campaigns|Back to Campaigns/i });
    await expect(returnBtn).toBeVisible({ timeout: 20_000 });
    await returnBtn.click();

    // The ?return= handoff lands back on Campaign 360 with ads data resolving.
    await expect(page).toHaveURL(ROUTES.campaign360, { timeout: 15_000 });
    const googleRowAfter = page.locator(MARKERS.integrationRow('google_ads'));
    await expect(googleRowAfter.locator(MARKERS.connectionState('connected'))).toBeVisible({
      timeout: 20_000,
    });
  });
});
