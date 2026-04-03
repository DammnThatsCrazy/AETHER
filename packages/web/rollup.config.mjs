import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';

import { readFileSync } from 'fs';
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'));
const SDK_VERSION = pkg.version;

export default {
  input: 'src/index.ts',
  output: [
    {
      file: 'dist/aether.cjs.js',
      format: 'cjs',
      exports: 'named',
      sourcemap: true,
      banner: `/* @aether/web v${SDK_VERSION} */`,
    },
    {
      file: 'dist/aether.esm.js',
      format: 'esm',
      sourcemap: true,
      banner: `/* @aether/web v${SDK_VERSION} */`,
    },
    {
      file: 'dist/aether.umd.js',
      format: 'umd',
      name: 'Aether',
      exports: 'named',
      sourcemap: true,
      banner: `/* @aether/web v${SDK_VERSION} */`,
      plugins: [terser()],
    },
  ],
  plugins: [
    resolve(),
    typescript({
      tsconfig: './tsconfig.build.json',
    }),
  ],
};
