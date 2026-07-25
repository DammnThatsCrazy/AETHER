import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@demo': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    globals: true,
    // VITE_DEMO_ENV has no default, so tests declare it explicitly too.
    env: { VITE_DEMO_ENV: 'local-mocked' },
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
