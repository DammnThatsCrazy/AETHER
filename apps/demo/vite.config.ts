import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const DEMO_ENVIRONMENTS = ['local', 'staging', 'production', 'test'] as const;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, 'VITE_');
  const demoEnv = env.VITE_DEMO_ENV;
  if (!demoEnv || !(DEMO_ENVIRONMENTS as readonly string[]).includes(demoEnv)) {
    throw new Error(
      `VITE_DEMO_ENV is required and must be one of: ${DEMO_ENVIRONMENTS.join(', ')}.`,
    );
  }
  for (const key of [
    'VITE_API_BASE_URL',
    'VITE_DEMO_TENANT_ID',
    'VITE_DEMO_SEED_NAMESPACE',
    'VITE_AETHER_URL',
    'VITE_KYBER_URL',
  ]) {
    if (!env[key]) throw new Error(`${key} is required.`);
  }

  return {
    plugins: [react()],
    publicDir: false,
    resolve: {
      alias: [{ find: '@demo', replacement: path.resolve(__dirname, 'src') }],
    },
    server: {
      port: 5177,
      proxy: {
        '/v1': { target: env.VITE_API_BASE_URL, changeOrigin: true },
      },
    },
    build: { sourcemap: true },
  };
});
