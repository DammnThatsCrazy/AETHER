import { defineConfig } from 'vitest/config';

/**
 * Vitest config for @aether/mobile-core.
 *
 * The core is platform-agnostic and runs directly in Node — the tests inject a stub
 * `fetch` + auth provider, so no device runtime is needed. `@aether/shared` resolves
 * through the workspace node_modules symlink.
 */
export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['src/**/__tests__/**/*.test.ts', 'src/**/*.test.ts'],
    reporters: ['default'],
  },
});
