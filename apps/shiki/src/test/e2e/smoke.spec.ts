import { test, expect } from '@playwright/test';

test.describe('SHIKI Smoke Tests', () => {
  test('app boots and redirects to mission', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/mission/);
  });

  test('shows SHIKI branding in sidebar', async ({ page }) => {
    await page.goto('/mission');
    await expect(page.locator('text=SHIKI')).toBeVisible();
  });

  test('mission page loads with health summary', async ({ page }) => {
    await page.goto('/mission');
    await expect(page.locator('text=Mission')).toBeVisible();
  });

  test('live page loads', async ({ page }) => {
    await page.goto('/live');
    await expect(page.locator('text=Live')).toBeVisible();
  });

  test('GOUF page loads', async ({ page }) => {
    await page.goto('/gouf');
    await expect(page.locator('text=GOUF')).toBeVisible();
  });

  test('entities page loads', async ({ page }) => {
    await page.goto('/entities');
    await expect(page.locator('text=Entities')).toBeVisible();
  });

  test('command page loads', async ({ page }) => {
    await page.goto('/command');
    // Scope to the page's H1 heading: 'text=Command' would otherwise also
    // match the 'engineering command' role badge rendered in the top-bar
    // on every authenticated page and trip Playwright's strict mode.
    await expect(page.getByRole('heading', { name: 'Command', level: 1 })).toBeVisible();
  });

  test('diagnostics page loads', async ({ page }) => {
    await page.goto('/diagnostics');
    await expect(page.locator('text=Diagnostics')).toBeVisible();
  });

  test('review page loads', async ({ page }) => {
    await page.goto('/review');
    await expect(page.locator('text=Review')).toBeVisible();
  });

  test('lab page loads', async ({ page }) => {
    await page.goto('/lab');
    await expect(page.locator('text=Lab')).toBeVisible();
  });

  test('sidebar navigation works', async ({ page }) => {
    await page.goto('/mission');
    await page.click('text=Live');
    await expect(page).toHaveURL(/\/live/);
    await page.click('text=GOUF');
    await expect(page).toHaveURL(/\/gouf/);
  });
});
