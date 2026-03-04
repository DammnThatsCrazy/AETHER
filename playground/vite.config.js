import { defineConfig } from 'vite';
import path from 'path';

// Resolve @aether/web to TypeScript source directly so Vite transpiles on-the-fly
// without requiring a separate build step.
export default defineConfig({
  resolve: {
    alias: {
      '@aether/web': path.resolve(__dirname, '../packages/web/src/index.ts'),
    },
  },
});
