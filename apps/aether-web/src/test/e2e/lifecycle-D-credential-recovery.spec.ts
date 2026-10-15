/**
 * Lifecycle E2E — Suite D: credential recovery.
 *
 * Scenario (plan §7 / D): revoked → degraded → impact disclosed → reconnect →
 * health restored.
 *
 * Serial journey over Suite tenant D (an activated tenant with a previously
 * connected Google Ads integration whose credential the seed has REVOKED). The
 * data-truth point of the suite: a revoked/degraded integration must never
 * render as Ready; the impact is disclosed and reconnect is a first-class CTA.
 * Reset the tenant seed (revoked state) before each run.
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

test.describe('Lifecycle D — credential recovery (Google Ads)', () => {
  test.skip(suiteGate('D'), suiteReason);

  test('D1: revoked integration renders degraded with impact disclosed', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('D')!);
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));

    const googleRow = page.locator(MARKERS.integrationRow('google_ads'));
    await expect(googleRow).toBeVisible({ timeout: 15_000 });

    // Honesty: the revoked credential reads Needs attention, never Ready.
    await expect(googleRow.locator(MARKERS.connectionState('needs_attention'))).toBeVisible({
      timeout: 20_000,
    });
    await expect(googleRow.locator(MARKERS.connectionState('ready'))).toHaveCount(0);

    // Impact is disclosed (not hidden behind a generic error).
    await expect(page.getByText(/revoked|credential.*invalid|reconnect to resume/i).first()).toBeVisible();
    const reconnectCta = page.getByRole('button', { name: /Reconnect/i }).first();
    await expect(reconnectCta).toBeVisible();
  });

  test('D2: reconnect restores health only after evidence', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('D')!);
    await goTo(page, ROUTES.settingsIntegrations, new RegExp(COPY.integrations));

    const googleRow = page.locator(MARKERS.integrationRow('google_ads'));
    await googleRow.getByRole('button', { name: /Reconnect/i }).click();

    // Re-grant the revoked credential (idempotent reconnect, WS-2).
    const refreshToken = page.locator(MARKERS.credentialField('google_ads', 'refresh_token'));
    await expect(refreshToken).toBeVisible({ timeout: 15_000 });
    await refreshToken.fill('e2e-google-refresh-token-restored');
    await page.getByRole('button', { name: /Reconnect|^Connect$/i }).click();

    // Health is restored from live credential evidence, not an optimistic flip.
    await expect(googleRow.locator(MARKERS.connectionState('connected'))).toBeVisible({
      timeout: 20_000,
    });
    await expect(googleRow.locator(MARKERS.connectionState('ready'))).toBeVisible({
      timeout: 30_000,
    });
    await expect(googleRow.locator(MARKERS.connectionState('needs_attention'))).toHaveCount(0);
  });
});
