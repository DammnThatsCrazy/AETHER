/**
 * Deployment environment types and helpers shared across the monorepo's
 * frontends and their Amplify build configuration.
 *
 * This module is deliberately I/O-free: it never reads `process.env` or
 * `import.meta.env` itself. Every helper takes the env-ish source record as a
 * parameter, so the same code runs unchanged under a Vite app
 * (`import.meta.env`), a Node build/deploy script (`process.env`), and a test
 * (a plain object) — the pattern each app's own `src/lib/env.ts` already uses
 * locally; this package gives the deploy tooling the same contract.
 */

export type DeploymentEnvironment = 'development' | 'staging' | 'production';

export interface EnvironmentConfig {
  readonly name: DeploymentEnvironment;
  readonly isProduction: boolean;
}

const KNOWN_ENVIRONMENTS: readonly DeploymentEnvironment[] = ['development', 'staging', 'production'];

/** Normalize an arbitrary, untrusted string into a known deployment
 * environment. Anything unrecognized (including undefined) resolves to
 * 'development' — the safest default for a build that has not declared one. */
export function resolveDeploymentEnvironment(raw: string | undefined): DeploymentEnvironment {
  const trimmed = raw?.trim();
  return (KNOWN_ENVIRONMENTS as readonly string[]).includes(trimmed ?? '')
    ? (trimmed as DeploymentEnvironment)
    : 'development';
}

/** The resolved environment plus the one derived flag every deploy config asks for. */
export function describeEnvironment(raw: string | undefined): EnvironmentConfig {
  const name = resolveDeploymentEnvironment(raw);
  return { name, isProduction: name === 'production' };
}

/**
 * Read one variable from an arbitrary env-ish source record — `process.env`,
 * `import.meta.env` (cast by the caller), or a plain object in a test — and
 * fall back to `fallback` when the key is absent or blank after trimming.
 * Never throws.
 */
export function readEnvVar(
  source: Readonly<Record<string, string | undefined>>,
  key: string,
  fallback: string,
): string {
  const value = source[key];
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed.length === 0 ? fallback : trimmed;
}

/** Same as `readEnvVar`, but returns `undefined` instead of a fallback when
 * the key is absent or blank — for genuinely optional configuration (a
 * secret, a feature flag) where "not set" must stay distinguishable from any
 * real value. */
export function readOptionalEnvVar(
  source: Readonly<Record<string, string | undefined>>,
  key: string,
): string | undefined {
  const value = source[key];
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed.length === 0 ? undefined : trimmed;
}
