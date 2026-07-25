// Demo environment contract.
//
// `VITE_DEMO_ENV` is required and explicit — there is no default. The valid
// values are the canonical deployment profiles the demo SPA can legitimately
// run as (see `config/deployment_profiles.yaml`):
//
//   local-mocked — MSW fixtures, no backend (runs: demo-spa, mock-data-msw)
//   demo-static  — static frontend, synthetic precomputed data, no backend
//   demo-live    — shared non-production backend, synthetic tenant, TTL cleanup
//
// An unset or unknown value fails the build in `vite.config.ts` and throws
// here, so a demo bundle can never silently fall back to mocked mode.
export const DEMO_ENVIRONMENTS = ['local-mocked', 'demo-static', 'demo-live'] as const;

export type DemoEnv = (typeof DEMO_ENVIRONMENTS)[number];

// Profiles whose data may be compiled into the bundle as synthetic fixtures.
// `demo-live` is excluded: its data comes from the shared non-production
// backend, so `src/data/fixtures.ts` is aliased out of that build entirely.
export const SYNTHETIC_DATASET_ENVIRONMENTS = ['local-mocked', 'demo-static'] as const;

// Every demo profile serves synthetic data; only the source differs. The UI
// label states which one so a viewer never mistakes the demo for a real tenant.
export const DEMO_DATA_SOURCE_LABEL: Record<DemoEnv, string> = {
  'local-mocked': 'in-browser MSW fixtures',
  'demo-static': 'precomputed synthetic dataset',
  'demo-live': 'synthetic tenant on a shared non-production backend',
};

export function assertDemoEnv(value: string | undefined): DemoEnv {
  const valid = DEMO_ENVIRONMENTS.join(', ');
  if (!value) {
    throw new Error(`VITE_DEMO_ENV is required and has no default. Set it to one of: ${valid}.`);
  }
  if (!(DEMO_ENVIRONMENTS as readonly string[]).includes(value)) {
    throw new Error(`VITE_DEMO_ENV="${value}" is not a demo profile. Expected one of: ${valid}.`);
  }
  return value as DemoEnv;
}

export function getDemoEnv(): DemoEnv {
  return assertDemoEnv(import.meta.env.VITE_DEMO_ENV as string | undefined);
}
