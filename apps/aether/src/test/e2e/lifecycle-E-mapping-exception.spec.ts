/**
 * Lifecycle E2E — Suite E: mapping exception.
 *
 * Scenario (plan §7 / E): ambiguous ad campaign → readiness review → Mapping
 * Review → resolve → Campaign 360 canonical identity updates.
 *
 * Serial journey over Suite tenant E (an activated tenant whose seed includes
 * an open/ambiguous mapping review and a canonical Aether campaign UUID to
 * resolve it to, supplied as E2E_CAMPAIGN_UUID). The Mapping Review and
 * campaign-quality surfaces already route in the tenant app (R1); the suite
 * drives the real exception → readiness-review → resolution → canonical
 * identity flow. Reset the tenant seed (open review present) before each run.
 */

import { expect, test } from '@playwright/test';
import {
  ROUTES,
  goTo,
  lifecycleSuiteCredentials,
  suiteGate,
  suiteReason,
  signIn,
} from './lifecycle.harness';

test.describe.configure({ mode: 'serial' });

const campaignUuid = process.env.E2E_CAMPAIGN_UUID ?? '';
const eGate = suiteGate('E') || !campaignUuid;
const eReason = campaignUuid
  ? suiteReason
  : 'requires E2E_CAMPAIGN_UUID (canonical campaign the seed resolves the review to)';

test.describe('Lifecycle E — mapping exception (ambiguous ad campaign)', () => {
  test.skip(eGate, eReason);

  test('E1: readiness review discloses the exception and routes into Mapping Review', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('E')!);

    // Campaign-quality readiness gate discloses open mapping reviews and links
    // the exception into the Mapping Review queue.
    await goTo(page, '/campaign-intelligence/quality', /Campaign Quality|Quality/i);
    const reviewQueueLink = page.getByRole('link', { name: /Review queue/i }).first();
    await expect(reviewQueueLink).toBeVisible({ timeout: 15_000 });
    await reviewQueueLink.click();

    await expect(page).toHaveURL(new RegExp(ROUTES.mappingReview), { timeout: 15_000 });
    await expect(page.getByRole('heading', { name: /Mapping Review/i })).toBeVisible();
  });

  test('E2: resolving the open review maps evidence to the canonical campaign', async ({ page }) => {
    await signIn(page, lifecycleSuiteCredentials('E')!);
    await goTo(page, ROUTES.mappingReview, /Mapping Review/i);

    // The default filter is 'open': at least one ambiguous review awaits.
    const resolveButtons = page.getByRole('button', { name: /Resolve this review by mapping to a campaign/i });
    const before = await resolveButtons.count();
    expect(before).toBeGreaterThan(0);

    // Resolve the first open review by assigning the canonical campaign UUID.
    await resolveButtons.first().click();
    const dialog = page.getByRole('dialog', { name: /Resolve mapping review/i });
    await expect(dialog).toBeVisible();
    await dialog.locator('#campaign-id-input').fill(campaignUuid);
    await dialog.getByRole('button', { name: /Confirm resolution/i }).click();

    // The resolved review leaves the open queue (row removed or queue empty).
    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
    if (before > 1) {
      await expect
        .poll(
          () => page.getByRole('button', { name: /Resolve this review by mapping to a campaign/i }).count(),
          { timeout: 15_000 }
        )
        .toBe(before - 1);
    } else {
      await expect(page.getByText(/All campaign evidence has been resolved/i)).toBeVisible({
        timeout: 15_000,
      });
    }

    // The canonical identity is durable: the resolved review shows under the
    // 'resolved' filter and no longer appears in the exception queue.
    await page.getByRole('group', { name: /Review status filter/i }).getByRole('button', { name: /resolved/i }).click();
    await expect(page.getByText(/resolved/i).first()).toBeVisible({ timeout: 15_000 });
  });
});
