// =============================================================================
// Aether SDK — LOADER BUILD CONFIG
// Separate Rollup config for the CDN auto-loader (~3KB minified+gzipped)
// Output: dist/loader.js (UMD) + dist/loader.mjs (ESM)
// =============================================================================

import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import { readFileSync } from 'fs';
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'));
const SDK_VERSION = pkg.version;

export default {
  // The CDN entry is the bootstrap, not the loader class: a snippet must work
  // with no follow-up JS, so the tag itself has to install the stub, read the
  // data-* attributes, and load + init the SDK. The AetherLoader class is
  // still exported for callers who want to drive loading themselves.
  input: 'src/loader/bootstrap.ts',
  output: [
    {
      file: 'dist/loader.js',
      format: 'umd',
      name: 'AetherLoader',
      exports: 'named',
      sourcemap: true,
      banner: `/* Aether SDK Loader v${SDK_VERSION} — https://cdn.aether.network/v1.js */`,
      plugins: [terser()],
    },
    {
      file: 'dist/loader.mjs',
      format: 'esm',
      sourcemap: true,
      banner: `/* Aether SDK Loader v${SDK_VERSION} — https://cdn.aether.network/sdk/v${SDK_VERSION.split('.')[0]}/loader.mjs */`,
      plugins: [terser()],
    },
  ],
  plugins: [
    resolve(),
    typescript({
      tsconfig: './tsconfig.build.json',
      declaration: false,
    }),
  ],
};
