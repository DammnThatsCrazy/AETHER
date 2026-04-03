// =============================================================================
// AETHER SDK — LOADER BUILD CONFIG
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
  input: 'src/loader/aether-loader.ts',
  output: [
    {
      file: 'dist/loader.js',
      format: 'umd',
      name: 'AetherLoader',
      exports: 'named',
      sourcemap: true,
      banner: `/* Aether SDK Loader v${SDK_VERSION} — cdn.aether.network/sdk/v${SDK_VERSION.split('.')[0]}/loader.js */`,
      plugins: [terser()],
    },
    {
      file: 'dist/loader.mjs',
      format: 'esm',
      sourcemap: true,
      banner: `/* Aether SDK Loader v${SDK_VERSION} — cdn.aether.network/sdk/v${SDK_VERSION.split('.')[0]}/loader.mjs */`,
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
