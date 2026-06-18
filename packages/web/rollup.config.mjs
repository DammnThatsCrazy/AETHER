import typescript from '@rollup/plugin-typescript';
import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';

import { readFileSync } from 'fs';
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'));
const SDK_VERSION = pkg.version;

const sharedPlugins = () => [
  resolve(),
  typescript({ tsconfig: './tsconfig.build.json' }),
];

export default [
  // Main SDK bundle
  {
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
    plugins: sharedPlugins(),
  },
  // Health subpath — SDKHealthAgent standalone bundle for @aether/web/health
  {
    input: 'src/health/index.ts',
    output: [
      {
        file: 'dist/health/index.js',
        format: 'esm',
        sourcemap: true,
        banner: `/* @aether/web/health v${SDK_VERSION} */`,
      },
    ],
    plugins: sharedPlugins(),
  },
  // React browser wrapper — @aether/web/react
  {
    input: 'src/react.tsx',
    external: ['react', 'react/jsx-runtime', '@aether/web'],
    output: [
      {
        file: 'dist/react.js',
        format: 'esm',
        sourcemap: true,
        banner: `/* @aether/web/react v${SDK_VERSION} */`,
      },
    ],
    plugins: sharedPlugins(),
  },
];
