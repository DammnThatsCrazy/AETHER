/**
 * Lifecycle E2E — Suite F: activation route convergence + tenant landing.
 *
 * Scenario (plan §4.6 compatibility route plan / Phase 2 landing):
 *
 *   F1 — /activate is a query-preserving alias: /activate?experience=… lands on
 *        /activation with the query intact and the guided activation surface.
 *   F2 — /activation is canonical: it renders directly (no redirect loop) and is
 *        the surface A1/A2 already drive.
 *   F3 — a COMPLETE tenant returning to / is restored to their last useful
 *        workspace (scope-scoped), not dropped on Home or /activation.
 *
 * Requires the R3/R4 integration env (WS-1..WS-6 merged, backend seeded) with a
 * completed tenant supplied as E2E_TENANT_EMAIL_F/_PASSWORD_F (or the shared
 * E2E_TENANT_EMAIL/PASSWORD). Suites run serial over their own tenant; F's
 * tenant must be seeded complete so F3's landing decision is the last-workspace
 * leg rather than the activation leg.
 */

import { expect, test } from '@playwright/test';
import {
  ROUTES,
  lifecycleSuiteCredentials,
  signIn,
  suiteGate,
  suiteReason,
} from './lifecycle.harness';

test.describe.configure({ mode: 'serial' });

const ACTIVATION_HEADING = 'Set up Aether around your goals';

/** Seed the per-user last-workspace preference in the real browser session. */
async function seedLastWorkspace(
  page: import('@playwright/test').Page,
  email: string,
  pathname: string,
): Promise<void> {
  await page.evaluate(
    ([key, value]) => window.localStorage.setItem(key, value),
    [`aether:last-workspace:${email}`, pathname] as const,
  );
}

test.describe('Lifecycle F — activation route convergence + tenant landing', () => {
  test.skip(suiteGate('F'), suiteReason);

  test('F1: /activate redirects to canonical /activation, preserving the query string', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('F')!);

    // Public/handoff CTAs reference /activate?experience=…; the alias hop must
    // carry the param into the canonical guided-activation URL.
    await page.goto(`${ROUTES.activateAlias}?experience=advertising_campaigns`);
    await expect(page).toHaveURL(/\/activation\?experience=advertising_campaigns$/, {
      timeout: 15_000,
    });
    // The guided-activation heading is unique to ActivatePage — the alias serves
    // the canonical surface, not the legacy bare step flow.
    await expect(page.getByRole('heading', { name: ACTIVATION_HEADING })).toBeVisible({
      timeout: 15_000,
    });
  });

  test('F2: /activation is canonical and renders directly without a redirect loop', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('F')!);

    await page.goto(ROUTES.activation);
    await expect(page.getByRole('heading', { name: ACTIVATION_HEADING })).toBeVisible({
      timeout: 15_000,
    });
    // Still on /activation (no bounce back to /activate or a *-alias).
    expect(new URL(page.url()).pathname).toBe(ROUTES.activation);
  });

  test('F3: a completed tenant is restored to their last useful workspace', async ({ page }) => {
    const creds = lifecycleSuiteCredentials('F')!;
    await signIn(page, creds);

    // F's tenant is complete; a prior session left them in Campaigns.
    await seedLastWorkspace(page, creds.email, ROUTES.campaignSources);
    await page.goto('/');
    // TenantLanding restores the scope-scoped workspace instead of Home.
    await expect(page).toHaveURL(ROUTES.campaignSources, { timeout: 15_000 });
  });
});
