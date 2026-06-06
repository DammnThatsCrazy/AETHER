import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['test/**/*.test.ts', 'src/**/*.test.ts'],
    reporters: ['default'],
    coverage: {
      provider: 'v8',
      all: false,
      thresholds: {
        lines: 65,
        branches: 65,
        functions: 55,
        statements: 65,
      },
    },
  },
});
