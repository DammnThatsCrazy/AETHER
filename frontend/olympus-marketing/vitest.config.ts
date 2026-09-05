import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: '@olympus-marketing',
        replacement: path.resolve(__dirname, 'src'),
      },
      // Resolve the workspace shared packages from source in clean frontend test
      // checkouts (the same aliasing the Aether suite uses).
      {
        find: /^@aether\/shared\/(.+)$/,
        replacement: `${path.resolve(__dirname, '../../packages/shared')}/$1`,
      },
      {
        find: '@aether/shared',
        replacement: path.resolve(__dirname, '../../packages/shared/index.ts'),
      },
    ],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    env: {
      VITE_OLYMPUS_ENV: 'test',
      VITE_AETHER_URL: 'https://aether.invalid',
    },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.mjs'],
  },
});
