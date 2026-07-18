import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  // Build identity injected at build time (drift-free: version from the
  // workspace package.json via npm, SHA/profile from CI env). Falls back to the
  // env-schema defaults for local dev / typecheck.
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(process.env.npm_package_version ?? 'dev'),
    'import.meta.env.VITE_GIT_SHA': JSON.stringify(
      process.env.GIT_SHA ?? process.env.GITHUB_SHA ?? process.env.VITE_GIT_SHA ?? 'dev',
    ),
    'import.meta.env.VITE_RELEASE_PROFILE': JSON.stringify(
      process.env.DEPLOYMENT_PROFILE ?? process.env.VITE_RELEASE_PROFILE ?? '',
    ),
  },
  resolve: {
    alias: {
      '@kyber': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          router: ['react-router-dom'],
          charts: ['recharts'],
          graph: ['cytoscape'],
        },
      },
    },
  },
});
