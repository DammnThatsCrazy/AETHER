import { z } from 'zod';

const envSchema = z.object({
  VITE_KYBER_ENV: z.enum(['local', 'staging', 'production', 'test']),
  VITE_API_BASE_URL: z.string().url(),
  VITE_AETHER_API_KEY: z.string().default(''),
  VITE_AETHER_ENDPOINT: z.string().url(),
  VITE_WS_BASE_URL: z.string().default('ws://localhost:8000'),
  VITE_GRAPHQL_URL: z.string().url().default('http://localhost:8000/v1/analytics/graphql'),
  VITE_OIDC_AUTHORITY: z.string().url().optional(),
  VITE_OIDC_CLIENT_ID: z.string().optional(),
  VITE_OIDC_REDIRECT_URI: z.string().url().optional(),
  VITE_OIDC_SCOPE: z.string().default('openid profile email groups'),
  VITE_AUTH0_DOMAIN: z.string().optional(),
  VITE_AUTH0_CLIENT_ID: z.string().optional(),
  VITE_AUTH0_AUDIENCE: z.string().optional(),
  VITE_AUTH0_REDIRECT_URI: z.string().url().optional(),
  VITE_AUTH0_LOGOUT_URI: z.string().url().optional(),
  VITE_SLACK_WEBHOOK_URL: z.string().url().optional(),
  VITE_AUTOMATION_POSTURE: z.enum(['conservative', 'balanced', 'aggressive']).default('conservative'),
  VITE_FEATURE_FLAGS: z.string().default('{}'),
  // Build identity (injected by vite define at build; 'dev' locally).
  VITE_APP_VERSION: z.string().default('dev'),
  VITE_GIT_SHA: z.string().default('dev'),
  VITE_RELEASE_PROFILE: z.string().default(''),
});

export class EnvironmentStartupError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EnvironmentStartupError';
  }
}

export type EnvConfig = z.infer<typeof envSchema>;

function loadEnv(): EnvConfig {
  const raw: Record<string, string | undefined> = {};
  for (const key of Object.keys(envSchema.shape)) {
    raw[key] = import.meta.env[key] as string | undefined;
  }
  if (raw.VITE_KYBER_ENV === 'local-live') {
    console.warn('[KYBER] VITE_KYBER_ENV=local-live is deprecated; use local. This compatibility path is live-only and cannot enable mocks.');
    raw.VITE_KYBER_ENV = 'local';
  }
  const result = envSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues.map(i => `  ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new EnvironmentStartupError(`[KYBER] Environment validation failed:\n${issues}`);
  }
  return result.data;
}

export const env = loadEnv();

export function getEnvironment() {
  return env.VITE_KYBER_ENV;
}

export function getRuntimeMode() {
  return 'live' as const;
}

export function isProduction() {
  return env.VITE_KYBER_ENV === 'production';
}

export function isLocalMocked() {
  return false;
}

/**
 * Whether `VITE_KYBER_ENV` was explicitly set. Missing values fail startup.
 */
export function isEnvExplicit() {
  const raw = import.meta.env.VITE_KYBER_ENV as string | undefined;
  return raw != null && raw !== '';
}

export function isMockAuthAllowed() {
  return env.VITE_KYBER_ENV === 'local' || env.VITE_KYBER_ENV === 'test';
}
