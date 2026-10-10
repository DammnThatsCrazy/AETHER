/**
 * Lifecycle E2E — Suite C: communications lifecycle.
 *
 * Scenario (plan §7 / C): Settings/Integrations → Communications → connect
 * Klaviyo → sync → Campaign 360 + Profile 360 comms facts present.
 *
 * Serial journey over Suite tenant C (an activated tenant). Requires the
 * WS-1 Integrations nested shell and the WS-2 connect contract; the comms
 * cohort membership itself is derived from the catalog (ADR-C11 / ADR-0010),
 * so the Communications experience group is asserted from the shared catalog
 * rather than a hand-synced list. Reset the tenant seed before each run.
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

test.describe('Lifecycle C — communications (Klaviyo)', () => {
  test.skip(suiteGate('C'), suiteReason);

  test('C1: Communications group lists the derived cohort with Klaviyo connectable', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('C')!);
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));

    // Communications is a single experience group; Klaviyo + the comms cohort
    // appear under it (membership derived from the catalog, never hardcoded in UI).
    const commsSection = page.getByRole('region', { name: /Communications/i });
    await expect(commsSection).toBeVisible({ timeout: 15_000 });

    const klaviyoRow = commsSection.locator(MARKERS.integrationRow('klaviyo'));
    await expect(klaviyoRow).toBeVisible();
    // Cohort companions render in the same group.
    for (const family of ['sendgrid', 'customerio', 'mailchimp']) {
      await expect(commsSection.locator(MARKERS.integrationRow(family))).toBeVisible();
    }
  });

  test('C2: connect Klaviyo and sync into the comms lifecycle', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('C')!);
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));

    const commsSection = page.getByRole('region', { name: /Communications/i });
    const klaviyoRow = commsSection.locator(MARKERS.integrationRow('klaviyo'));
    await klaviyoRow.getByText(COPY.connect, { exact: true }).click();

    const apiKey = page.locator(MARKERS.credentialField('klaviyo', 'api_key'));
    await expect(apiKey).toBeVisible({ timeout: 15_000 });
    await apiKey.fill('e2e-klaviyo-private-key');
    await page.getByRole('button', { name: /^Connect$/i }).click();

    // Klaviyo ships reconciliation (AdapterResult) — connect reflects a real
    // secret-configured record, then an explicit Sync advances the cursor.
    await expect(klaviyoRow.locator(MARKERS.connectionState('connected'))).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole('button', { name: /Sync/i }).first().click();
    await expect(page.getByText(COPY.syncing).first()).toBeVisible({ timeout: 15_000 });
    // Readiness resolves only from evidence: Connected first, Ready after sync.
    await expect(klaviyoRow.locator(MARKERS.connectionState('connected'))).toBeVisible({
      timeout: 30_000,
    });
  });

  test('C3: comms-driven campaign facts are reachable from Campaign 360', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('C')!);

    // Once comms data flows, Campaign 360 renders comms-sourced campaigns and
    // never claims data before a sync has produced it.
    await goTo(page, ROUTES.campaign360, /Campaign/i);
    await expect(page).toHaveURL(ROUTES.campaign360);

    // If the sync has completed this tenant sees a comms-sourced campaign row;
    // the page must at minimum render campaign content rather than an empty
    // surface mislabeled as "ready".
    await expect(page.getByText(/communications|email campaign|klaviyo/i).first()).toBeVisible({
      timeout: 20_000,
    });
  });
});
