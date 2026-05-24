import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import mdx from '@mdx-js/rollup';
import remarkFrontmatter from 'remark-frontmatter';
import remarkMdxFrontmatter from 'remark-mdx-frontmatter';
import path from 'path';

// Tier-to-output-dir mapping.
// VITE_TIER is set by the build:public/portal/internal npm scripts.
// The default tier is 'P' (public) so `npm run build` (CI) always
// produces the most-conservative bundle.
const tier = (process.env['VITE_TIER'] ?? 'P') as 'P' | 'C' | 'I';
const outDirMap: Record<typeof tier, string> = {
  P: 'out-public',
  C: 'out-portal',
  I: 'out-internal',
};

// MDX is processed before React so enforce: 'pre' is required.
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
  define: {
    // Expose tier to the client bundle so App.tsx can filter by visibility.
    'import.meta.env.VITE_TIER': JSON.stringify(tier),
  },
  resolve: {
    alias: {
      '@docs': path.resolve(__dirname, 'src'),
      '@content': path.resolve(__dirname, '../../docs'),
    },
  },
  server: {
    port: 5176,
    fs: {
      allow: [path.resolve(__dirname, '../..'), path.resolve(__dirname)],
    },
  },
  build: {
    sourcemap: true,
    // `npm run build` (CI / dev) → dist  so existing CI step still passes.
    // `npm run build:public/portal/internal` → tier-specific dirs.
    outDir: process.env['VITE_TIER'] ? outDirMap[tier] : 'dist',
  },
});
