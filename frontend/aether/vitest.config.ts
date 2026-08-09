import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: '@aether-app',
        replacement: path.resolve(__dirname, 'src'),
      },
      // Resolve package subpaths from source in clean frontend test checkouts.
      // The workspace package exports dist/*, but CI intentionally does not
      // publish its generated dist tree before running the Aether suite.
      {
        find: /^@aether\/shared\/(.+)$/,
        replacement: `${path.resolve(__dirname, '../../packages/shared')}/$1`,
      },
      // Resolve the workspace web SDK from source in tests: its dist/ entry is
      // gitignored and not built in the frontend CI job, so package-entry
      // resolution fails there (same aliasing the SDK's own vitest config uses).
      {
        find: '@aether/web',
        replacement: path.resolve(__dirname, '../../packages/web/src/index.ts'),
      },
      // Payment and capability components import the shared contract barrel.
      // Its published entry targets dist/, which is intentionally absent in a
      // clean frontend test checkout, so resolve this workspace dependency from
      // source just as we do for the web SDK above.
      {
        find: '@aether/shared',
        replacement: path.resolve(__dirname, '../../packages/shared/index.ts'),
      },
    ],
  },
  test: {
    globals: true,
    // Heavy jsdom component tests (multi-panel pages, userEvent typing into
    // several fields with debounced captures) border the 5s vitest default
    // and flake under parallel CI workers. Generous per-suite budget.
    testTimeout: 15_000,
    environment: 'jsdom',
    env: {
      VITE_AETHER_ENV: 'test',
      VITE_API_BASE_URL: 'http://localhost:8000',
      VITE_AETHER_ENDPOINT: 'http://localhost:8000',
    },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
});
