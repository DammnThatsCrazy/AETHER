import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import mdx from '@mdx-js/rollup';
import remarkFrontmatter from 'remark-frontmatter';
import remarkMdxFrontmatter from 'remark-mdx-frontmatter';
import path from 'path';

// MDX is processed before React so enforce: 'pre' is required.
// Three build outputs land in slice 4 (out-public / out-portal / out-internal),
// routed by frontmatter `visibility:` field.
export default defineConfig({
  plugins: [
    {
      enforce: 'pre',
      ...mdx({
        remarkPlugins: [remarkFrontmatter, [remarkMdxFrontmatter, { name: 'frontmatter' }]],
      }),
    },
    react(),
  ],
  resolve: {
    alias: {
      '@docs': path.resolve(__dirname, 'src'),
      // Allow importing from the repo-level docs tree
      '@content': path.resolve(__dirname, '../../docs'),
    },
  },
  // Allow Vite to serve files from the repo-level docs tree
  server: {
    port: 5176,
    fs: {
      allow: [path.resolve(__dirname, '../..'), path.resolve(__dirname)],
    },
  },
  build: {
    sourcemap: true,
    outDir: 'dist',
  },
});
