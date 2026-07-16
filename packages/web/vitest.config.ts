import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  resolve: {
    alias: [
      {
        find: /^@aether\/web$/,
        replacement: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
      },
    ],
  },
  test: {
    environment: 'node',
    globals: false,
    include: ['test/**/*.test.ts', 'test/**/*.test.tsx', 'src/**/*.test.ts', 'src/**/*.test.tsx'],
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
