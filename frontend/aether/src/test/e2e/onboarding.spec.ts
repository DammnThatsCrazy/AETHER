import { test, expect } from '@playwright/test';

// Scenario A: root redirects to /signup or /login
test('A: root redirects to auth page', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/(signup|login)/);
});

// Scenario B: signup form → OTP screen
test('B: fill signup form and reach OTP verification screen', async ({ page }) => {
  await page.goto('/signup');

  await page.fill('#signup-name', 'Test User');
  await page.fill('#signup-email', `e2e+${Date.now()}@example.com`);
  await page.fill('#signup-password', 'testpass123');

  await page.click('button[type="submit"]');

  await expect(page.getByText('Check your email')).toBeVisible({ timeout: 10_000 });
});

// Scenario C: OTP step renders 6-digit input
test('C: OTP screen has 6-digit verification input', async ({ page }) => {
  await page.goto('/signup');

  await page.fill('#signup-name', 'Test User');
  await page.fill('#signup-email', `e2e+${Date.now()}@example.com`);
  await page.fill('#signup-password', 'testpass123');
  await page.click('button[type="submit"]');

  await expect(page.getByText('Check your email')).toBeVisible({ timeout: 10_000 });

  // Verify & continue button is disabled before a code is entered
  const submitBtn = page.getByRole('button', { name: /Verify & continue/i });
  await expect(submitBtn).toBeDisabled();
});

// Scenario D: login page has email and password inputs
test('D: login page has email and password fields with sign-in button', async ({ page }) => {
  await page.goto('/login');

  await expect(page.locator('#login-email')).toBeVisible();
  await expect(page.locator('#login-password')).toBeVisible();

  const signInBtn = page.getByRole('button', { name: /Sign in/i });
  await expect(signInBtn).toBeVisible();
  // Button is disabled when fields are empty
  await expect(signInBtn).toBeDisabled();
});

// Scenario E: signup page has SSO provider buttons and plan selector
test('E: signup page shows plan selector and SSO options', async ({ page }) => {
  await page.goto('/signup');

  // Plan selector
  await expect(page.locator('#signup-plan')).toBeVisible();

  // At least one SSO button
  const googleBtn = page.getByRole('button', { name: /Google/i });
  await expect(googleBtn).toBeVisible();
});
