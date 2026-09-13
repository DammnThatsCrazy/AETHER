import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['tests/**/*.ts'],
    exclude: ['tests/fixtures/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: ['packages/*/src/**/*.ts', 'services/*/src/**/*.ts'],
    },
    testTimeout: 10_000,
  },
  resolve: {
    alias: {
      '@aether/common': resolve(__dirname, 'packages/common/src'),
      '@aether/auth': resolve(__dirname, 'packages/auth/src'),
      '@aether/logger': resolve(__dirname, 'packages/logger/src'),
      '@aether/events': resolve(__dirname, 'packages/events/src'),
      '@aether/cache': resolve(__dirname, 'packages/cache/src'),
    },
  },
});
