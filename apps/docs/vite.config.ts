import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Three build outputs are planned (public / portal / internal), routed
// by frontmatter `visibility:` (see scripts/docs_schema.json). The
// current slice ships only the workspace skeleton and a hello page —
// follow-up slices add MDX rendering, generated-artifact consumption,
// and the multi-tier output bundling.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@docs': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5176,
  },
  build: {
    sourcemap: true,
    outDir: 'dist',
  },
});
