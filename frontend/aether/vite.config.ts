import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@aether-app': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5175,
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      // Exclude MSW from production bundles — it's only used in local-mocked mode
      external: (id) => id.includes('msw') && process.env.VITE_AETHER_ENV !== 'local-mocked',
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react-dom')) return 'react-dom';
          if (id.includes('node_modules/react')) return 'react';
          if (id.includes('node_modules/react-router')) return 'router';
          if (id.includes('node_modules/@auth0')) return 'auth0';
          if (id.includes('node_modules/zod')) return 'zod';
          if (id.includes('frontend/shared/src')) return 'ui';
        },
      },
    },
  },
});
