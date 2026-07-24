import { test, expect } from '@playwright/test';

test.describe('KYBER Smoke Tests', () => {
  test('app boots and redirects to mission', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/mission/);
  });

  test('shows the unauthenticated sign-in surface', async ({ page }) => {
    await page.goto('/mission');
    await expect(page.getByText('KYBER', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with SSO' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Main navigation' })).not.toBeVisible();
  });

  for (const route of [
    '/mission',
    '/live',
    '/noesis',
    '/entities',
    '/command',
    '/diagnostics',
    '/review',
    '/lab',
  ]) {
    test(`${route} requires a backend-authenticated session`, async ({ page }) => {
      await page.goto(route);
      await expect(page.getByRole('button', { name: 'Sign in with SSO' })).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Main navigation' })).not.toBeVisible();
    });
  });
});
