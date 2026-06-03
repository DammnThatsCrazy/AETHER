import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@demo': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5177,
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      external: (id) => id.includes('msw') && process.env.VITE_DEMO_ENV !== 'local-mocked',
    },
  },
});
