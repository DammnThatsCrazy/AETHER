import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@kyber': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    globals: true,
    // Heavy jsdom component tests (multi-panel pages, userEvent typing into
    // several fields with debounced captures) border the 5s vitest default
    // and flake under parallel CI workers. Generous per-suite budget.
    testTimeout: 15_000,
    environment: 'jsdom',
    env: {
      VITE_KYBER_ENV: 'test',
      VITE_API_BASE_URL: 'http://localhost:8000',
      VITE_AETHER_ENDPOINT: 'http://localhost:8000',
    },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'src/test/unit/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
});
