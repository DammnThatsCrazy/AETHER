import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { manualChunks } from './chunks';
import { platformVersion } from './platform-version';

export default defineConfig({
  plugins: [react()],
  define: {
    __PLATFORM_VERSION__: JSON.stringify(platformVersion()),
  },
  // The Olympus Arch and Aether Layers marks are owned by packages/brand so
  // every build serves the same reviewed SVGs.
  publicDir: path.resolve(__dirname, '../../packages/brand/src/identity/marks'),
  resolve: {
    alias: {
      '@site': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5180,
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
});
