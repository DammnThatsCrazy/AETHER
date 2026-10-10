export const DEMO_ENVIRONMENTS = ['local', 'staging', 'production', 'test'] as const;
export type DemoEnvironment = (typeof DEMO_ENVIRONMENTS)[number];

export interface DemoConfig {
  readonly environment: DemoEnvironment;
  readonly apiBaseUrl: string;
  readonly tenantId: string;
  readonly seedNamespace: string;
  readonly aetherUrl: string;
  readonly kyberUrl: string;
}

export class DemoEnvironmentStartupError extends Error {
  readonly name = 'DemoEnvironmentStartupError';
}

function required(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (!normalized) throw new DemoEnvironmentStartupError(`${name} is required.`);
  return normalized;
}

function url(name: string, value: string | undefined, environment: DemoEnvironment): string {
  const raw = required(name, value);
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new DemoEnvironmentStartupError(`${name} must be an absolute URL.`);
  }
  if (environment === 'production' && parsed.protocol !== 'https:') {
    throw new DemoEnvironmentStartupError(`${name} must use HTTPS in production.`);
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new DemoEnvironmentStartupError(`${name} must use HTTP or HTTPS.`);
  }
  return parsed.toString().replace(/\/$/, '');
}

export function assertDemoEnvironment(value: string | undefined): DemoEnvironment {
  const raw = required('VITE_DEMO_ENV', value);
  if (!(DEMO_ENVIRONMENTS as readonly string[]).includes(raw)) {
    throw new DemoEnvironmentStartupError(
      `VITE_DEMO_ENV="${raw}" is invalid. Expected one of: ${DEMO_ENVIRONMENTS.join(', ')}.`,
    );
  }
  return raw as DemoEnvironment;
}

export function parseDemoConfig(env: Record<string, string | undefined>): DemoConfig {
  const environment = assertDemoEnvironment(env.VITE_DEMO_ENV);
  return {
    environment,
    apiBaseUrl: url('VITE_API_BASE_URL', env.VITE_API_BASE_URL, environment),
    tenantId: required('VITE_DEMO_TENANT_ID', env.VITE_DEMO_TENANT_ID),
    seedNamespace: required('VITE_DEMO_SEED_NAMESPACE', env.VITE_DEMO_SEED_NAMESPACE),
    aetherUrl: url('VITE_AETHER_URL', env.VITE_AETHER_URL, environment),
    kyberUrl: url('VITE_KYBER_URL', env.VITE_KYBER_URL, environment),
  };
}

export function getDemoConfig(): DemoConfig {
  return parseDemoConfig(import.meta.env as Record<string, string | undefined>);
}
