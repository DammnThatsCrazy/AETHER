import { getEnvironment } from '@kyber/lib/env';

export function useLabData() {
  const environment = getEnvironment();
  return {
    environment,
    available: false,
    message: 'Fixture inspection and export were removed from the runtime application. Use backend diagnostics for operational data.',
  };
}
