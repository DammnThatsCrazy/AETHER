import { defineConfig } from 'vite';
import path from 'path';

// Resolve @olympuslabs/aether-web to TypeScript source directly so Vite transpiles on-the-fly
// without requiring a separate build step.
export default defineConfig({
  resolve: {
    alias: {
      '@olympuslabs/aether-web': path.resolve(__dirname, '../web/src/index.ts'),
    },
  },
});
