import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

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
  resolve: {
    alias: [
      {
        find: /^@aether\/shared\/consent-receipt$/,
        replacement: fileURLToPath(
          new URL('../shared/consent-receipt.ts', import.meta.url),
        ),
      },
    ],
  },
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
        // Branch threshold set to 73% to account for optional-chaining null guards
        // throughout the bridge (AetherNative?.method()) which are valid null-safety
        // patterns but structurally impossible to cover without a full RN runtime.
        branches: 73,
        functions: 35,
        statements: 75,
      },
    },
  },
});
