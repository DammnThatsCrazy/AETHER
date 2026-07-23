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
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
});
