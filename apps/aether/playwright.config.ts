import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);
const stagingBaseURL = process.env.IDENTITY_STAGING_UI_BASE_URL;

export default defineConfig({
  testDir: './src/test/e2e',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ? resolve(process.env.PLAYWRIGHT_OUTPUT_DIR) : 'test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: stagingBaseURL || 'http://localhost:5175',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  ...(stagingBaseURL ? {} : { webServer: {
    // The application intentionally refuses an implicit runtime profile.
    // Make the E2E server's backend-only test profile explicit at the npm/Vite
    // process boundary, including on clean CI runners.
    command: [
      'VITE_AETHER_ENV=test',
      'VITE_API_BASE_URL=http://localhost:8000',
      'VITE_AETHER_ENDPOINT=http://localhost:8000',
      'npm run dev -- --mode test',
    ].join(' '),
    port: 5175,
    reuseExistingServer: !process.env.CI,
    env: {
      ...inheritedEnvironment,
      VITE_AETHER_ENV: 'test',
      VITE_API_BASE_URL: 'http://localhost:8000',
      VITE_AETHER_ENDPOINT: 'http://localhost:8000',
      // The identity continuity E2E harness mounts the real dashboard behind
      // its normal tenant feature gate. This remains an E2E-only runtime flag.
      VITE_FEATURE_FLAGS: JSON.stringify({
        identity_explainability_enabled: true,
        tenant_identity_activation_dashboard_enabled: true,
      }),
    },
  } }),
});
