// =============================================================================
// AETHER SDK — LOADER BUILD CONFIG
// Separate Rollup config for the CDN auto-loader (~3KB minified+gzipped)
// Output: dist/loader.js (UMD) + dist/loader.mjs (ESM)
// =============================================================================

import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';

export default {
  input: 'src/loader/aether-loader.ts',
  output: [
    {
      file: 'dist/loader.js',
      format: 'umd',
      name: 'AetherLoader',
      exports: 'named',
      sourcemap: true,
      banner: '/* Aether SDK Loader v5.0 — cdn.aether.network/sdk/v5/loader.js */',
      plugins: [terser()],
    },
    {
      file: 'dist/loader.mjs',
      format: 'esm',
      sourcemap: true,
      banner: '/* Aether SDK Loader v5.0 — cdn.aether.network/sdk/v5/loader.mjs */',
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
