import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './src/test/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:5175',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    port: 5175,
    reuseExistingServer: !process.env.CI,
    env: {
      // Disable local-mocked auth so unauthenticated routes redirect to /login
      // rather than auto-logging in the mock user. Required for E2E tests to
      // reach /signup and /login pages.
      VITE_AETHER_ENV: 'staging',
    },
  },
});
