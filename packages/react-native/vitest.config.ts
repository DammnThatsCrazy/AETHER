import { defineConfig } from 'vitest/config';

/**
 * Vitest config for the React Native SDK.
 *
 * React Native code can't be executed directly in Node (no native bridge),
 * so each test file installs a lightweight mock of `react-native` via
 * vi.mock() before importing the module under test. These tests exercise
 * the bridge's happy-path and null-guard behaviour — they do NOT boot the
 * native runtime.
 */
export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['src/**/__tests__/**/*.test.ts', 'src/**/*.test.ts'],
    reporters: ['default'],
    coverage: {
      provider: 'v8',
      all: false,
      thresholds: {
        lines: 75,
        branches: 80,
        functions: 35,
        statements: 75,
      },
    },
  },
});
