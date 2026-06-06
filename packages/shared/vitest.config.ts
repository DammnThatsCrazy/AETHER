import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: ['*.test.ts', '__tests__/**/*.test.ts'],
    reporters: ['default'],
    coverage: {
      provider: 'v8',
      all: false,
      thresholds: {
        lines: 95,
        branches: 80,
        functions: 95,
        statements: 95,
      },
    },
  },
});
