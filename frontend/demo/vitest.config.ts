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
    env: {
      VITE_DEMO_ENV: 'test',
      VITE_API_BASE_URL: 'https://api.invalid',
      VITE_DEMO_TENANT_ID: 'test-demo',
      VITE_DEMO_SEED_NAMESPACE: 'test',
      VITE_AETHER_URL: 'https://aether.invalid',
      VITE_KYBER_URL: 'https://kyber.invalid',
    },
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
