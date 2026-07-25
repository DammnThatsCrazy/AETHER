import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Mirrors src/lib/env.ts; scripts/validate_frontend_data_truth.py asserts both
// lists still match the canonical profiles in config/deployment_profiles.yaml.
const DEMO_ENVIRONMENTS = ['local-mocked', 'demo-static', 'demo-live'] as const;
const SYNTHETIC_DATASET_ENVIRONMENTS = ['local-mocked', 'demo-static'] as const;

export default defineConfig(({ mode }) => {
  // loadEnv merges .env files with prefixed process.env values, so this is the
  // same value the client receives as import.meta.env.VITE_DEMO_ENV.
  const demoEnv = loadEnv(mode, __dirname, 'VITE_').VITE_DEMO_ENV;
  const valid = DEMO_ENVIRONMENTS.join(', ');
  if (!demoEnv) {
    throw new Error(
      `VITE_DEMO_ENV is required and has no default — refusing to build the demo app. Set it to one of: ${valid}.`,
    );
  }
  if (!(DEMO_ENVIRONMENTS as readonly string[]).includes(demoEnv)) {
    throw new Error(`VITE_DEMO_ENV="${demoEnv}" is not a demo profile. Expected one of: ${valid}.`);
  }
  const shipsSyntheticDataset = (SYNTHETIC_DATASET_ENVIRONMENTS as readonly string[]).includes(demoEnv);

  return {
    plugins: [react()],
    // public/ holds only the MSW worker script, and Vite copies publicDir into
    // every build. Outside local-mocked it must not be emitted at all.
    publicDir: demoEnv === 'local-mocked' ? 'public' : false,
    resolve: {
      alias: [
        // demo-live serves the synthetic tenant from the shared non-production
        // backend, so the fixture module must not resolve at all.
        ...(shipsSyntheticDataset
          ? []
          : [{
              find: /^@demo\/data\/dataset$/,
              replacement: path.resolve(__dirname, 'src/data/dataset.live.ts'),
            }]),
        { find: '@demo', replacement: path.resolve(__dirname, 'src') },
      ],
    },
    server: {
      port: 5177,
      proxy: {
        '/v1': { target: 'http://localhost:8000', changeOrigin: true },
      },
    },
    build: {
      sourcemap: true,
      rollupOptions: {
        external: (id: string) => id.includes('msw') && demoEnv !== 'local-mocked',
      },
    },
  };
});
