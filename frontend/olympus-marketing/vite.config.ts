import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  // Canonical Olympus/Aether identity geometry is package-owned so every
  // product build serves the exact same reviewed SVG assets.
  publicDir: path.resolve(__dirname, '../../packages/brand/src/identity/marks'),
  // Build identity injected at build time (drift-free: version from the
  // workspace package.json via npm, SHA/profile from CI env). Falls back to the
  // env defaults for local dev / typecheck.
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
      '@olympus-marketing': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5178,
  },
  build: {
    sourcemap: true,
    commonjsOptions: {
      // @aether/shared ships CJS-only. Extend the default node_modules include
      // to also cover the workspace package so Rollup resolves named exports.
      include: [/node_modules/, /packages\/shared/],
    },
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react-dom')) return 'react-dom';
          if (id.includes('node_modules/react')) return 'react';
          if (id.includes('node_modules/react-router')) return 'router';
          if (id.includes('frontend/shared/src')) return 'ui';
        },
      },
    },
  },
});
