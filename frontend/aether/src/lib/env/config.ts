import { z } from 'zod';

const envSchema = z.object({
  VITE_AETHER_ENV: z.enum(['local', 'staging', 'production', 'test']),
  VITE_API_BASE_URL: z.string().url(),
  VITE_AETHER_API_KEY: z.string().default(''),
  VITE_AETHER_ENDPOINT: z.string().url(),
  VITE_OIDC_AUTHORITY: z.string().url().optional(),
  VITE_OIDC_CLIENT_ID: z.string().optional(),
  VITE_OIDC_REDIRECT_URI: z.string().url().optional(),
  VITE_OIDC_SCOPE: z.string().default('openid profile email'),
  VITE_AUTH0_DOMAIN: z.string().optional(),
  VITE_AUTH0_CLIENT_ID: z.string().optional(),
  VITE_AUTH0_AUDIENCE: z.string().optional(),
  VITE_AUTH0_REDIRECT_URI: z.string().url().optional(),
  VITE_AUTH0_LOGOUT_URI: z.string().url().optional(),
  VITE_STRIPE_PUBLISHABLE_KEY: z.string().optional(),
  VITE_ENTERPRISE_EMAIL_VERIFIED: z.string().default('false'),
  VITE_ENTERPRISE_EMAIL: z.string().default('sales@aether.dev'),
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
  if (raw.VITE_AETHER_ENV === 'local-live') {
    console.warn('[AETHER] VITE_AETHER_ENV=local-live is deprecated; use local. This compatibility path is live-only and cannot enable mocks.');
    raw.VITE_AETHER_ENV = 'local';
  }
  const result = envSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues.map(i => `  ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new EnvironmentStartupError(`[AETHER] Environment validation failed:\n${issues}`);
  }
  return result.data;
}

export const env = loadEnv();

export function getEnvironment() {
  return env.VITE_AETHER_ENV;
}

export function getRuntimeMode() {
  return 'live' as const;
}

export function isLocalMocked() {
  return false;
}

/**
 * Whether `VITE_AETHER_ENV` was explicitly set. Missing values fail startup.
 */
export function isEnvExplicit() {
  const raw = import.meta.env.VITE_AETHER_ENV as string | undefined;
  return raw != null && raw !== '';
}

export function isProduction() {
  return env.VITE_AETHER_ENV === 'production';
}

export function isMockAuthAllowed() {
  return env.VITE_AETHER_ENV === 'local' || env.VITE_AETHER_ENV === 'test';
}
