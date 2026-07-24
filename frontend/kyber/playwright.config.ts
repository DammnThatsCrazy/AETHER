import { defineConfig, devices } from '@playwright/test';

const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);

export default defineConfig({
  testDir: './src/test/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:5174',
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
    env: {
      ...inheritedEnvironment,
      VITE_KYBER_ENV: 'test',
      VITE_API_BASE_URL: 'http://localhost:8000',
      VITE_AETHER_ENDPOINT: 'http://localhost:8000',
    },
    port: 5174,
    reuseExistingServer: !process.env.CI,
  },
});
