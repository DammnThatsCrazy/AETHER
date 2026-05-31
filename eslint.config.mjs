import js from '@eslint/js';
import tsTranspileParser from './scripts/eslint/typescript-transpile-parser.mjs';

const tsFiles = [
  'packages/**/*.{ts,tsx}',
  'frontend/**/*.{ts,tsx}',
];

export default [
  {
    ignores: [
      '**/dist/**',
      '**/node_modules/**',
      '**/coverage/**',
      '**/.vite/**',
      '**/*.d.ts',
    ],
  },
  js.configs.recommended,
  {
    files: tsFiles,
    languageOptions: {
      parser: tsTranspileParser,
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      // TypeScript owns symbol, type-only import, and JSX semantic checks via
      // each workspace's `tsc --noEmit` typecheck. ESLint remains a JS-syntax
      // lint gate for reachable runtime code without requiring an unpinned
      // third-party TypeScript parser in CI.
      'no-undef': 'off',
      'no-unused-vars': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-extra-boolean-cast': 'off',
    },
  },
  {
    rules: {
      'react-hooks/exhaustive-deps': 'off',
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', '**/test/**/*.{ts,tsx}', '**/__tests__/**/*.{ts,tsx}'],
  },
];
