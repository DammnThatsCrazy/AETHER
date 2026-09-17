import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const alias = [
  { find: /^react-native$/, replacement: fileURLToPath(new URL('./tests/mocks/react-native.ts', import.meta.url)) },
  { find: /@aether\/react-native/, replacement: fileURLToPath(new URL('./packages/react-native/src/bridge.ts', import.meta.url)) },
  { find: /@aether\/proof-contracts/, replacement: fileURLToPath(new URL('./packages/proof-contracts/src/index.ts', import.meta.url)) },
  { find: /@aether\/proof-fixtures/, replacement: fileURLToPath(new URL('./packages/proof-fixtures/src/index.ts', import.meta.url)) },
];

export default defineConfig({
  test: {
    environment: 'node',
    globals: false,
    include: [
      'tests/contracts/**/*.test.ts',
      'tests/sdk/**/*.test.ts',
      'tests/connectors/**/*.test.ts',
      'tests/identity/**/*.test.ts',
      'tests/journeys/**/*.test.ts',
      'tests/campaigns/**/*.test.ts',
      'tests/value/**/*.test.ts',
      'tests/lenses/**/*.test.ts',
      'tests/e2e/**/*.test.ts',
      'tests/graph/**/*.test.ts',
    ],
    reporters: ['default'],
    server: {
      deps: {
        inline: [/react-native/, /@aether\/react-native/],
      },
    },
    resolve: {
      alias,
    },
  },
  resolve: {
    alias,
  },
});
