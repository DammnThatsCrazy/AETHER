import { defineConfig } from 'vitest/config';

/**
 * Vitest config for @aether/mobile-ui.
 *
 * Unit tests target the pure, runtime-light parts of the kit — the theme token
 * object and the navigator registry state machine — neither of which imports
 * react-native, so they run directly in Node. The React Native `Screen` container
 * and the shared components are exercised by the apps' M3/M4 typecheck/build
 * gates rather than by unit tests here.
 */
export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['src/**/__tests__/**/*.test.ts', 'src/**/__tests__/**/*.test.tsx'],
    reporters: ['default'],
  },
});
