import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';
import { platformVersion } from './platform-version';

export default defineConfig({
  plugins: [react()],
  define: {
    __PLATFORM_VERSION__: JSON.stringify(platformVersion()),
  },
  resolve: {
    alias: {
      '@site': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
