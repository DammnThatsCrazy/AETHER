import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@aether-app': path.resolve(__dirname, 'src'),
      // Resolve the workspace web SDK from source in tests: its dist/ entry is
      // gitignored and not built in the frontend CI job, so package-entry
      // resolution fails there (same aliasing the SDK's own vitest config uses).
      '@aether/web': path.resolve(__dirname, '../../packages/web/src/index.ts'),
      // Payment and capability components import the shared contract barrel.
      // Its published entry targets dist/, which is intentionally absent in a
      // clean frontend test checkout, so resolve this workspace dependency from
      // source just as we do for the web SDK above.
      '@aether/shared': path.resolve(__dirname, '../../packages/shared/index.ts'),
    },
  },
  test: {
    globals: true,
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
