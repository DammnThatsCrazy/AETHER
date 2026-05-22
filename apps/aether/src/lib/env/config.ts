import { z } from 'zod';

const envSchema = z.object({
  VITE_AETHER_ENV: z.enum(['local-mocked', 'local-live', 'staging', 'production']).default('local-mocked'),
  VITE_API_BASE_URL: z.string().url().default('http://localhost:8000'),
  VITE_AETHER_API_KEY: z.string().default(''),
  VITE_AETHER_ENDPOINT: z.string().url().default('http://localhost:8000'),
  VITE_OIDC_AUTHORITY: z.string().url().optional(),
  VITE_OIDC_CLIENT_ID: z.string().optional(),
  VITE_OIDC_REDIRECT_URI: z.string().url().optional(),
  VITE_OIDC_SCOPE: z.string().default('openid profile email'),
  VITE_AUTH0_DOMAIN: z.string().optional(),
  VITE_AUTH0_CLIENT_ID: z.string().optional(),
  VITE_AUTH0_AUDIENCE: z.string().optional(),
  VITE_AUTH0_REDIRECT_URI: z.string().url().optional(),
  VITE_AUTH0_LOGOUT_URI: z.string().url().optional(),
});

export type EnvConfig = z.infer<typeof envSchema>;

function loadEnv(): EnvConfig {
  const raw: Record<string, string | undefined> = {};
  for (const key of Object.keys(envSchema.shape)) {
    raw[key] = import.meta.env[key] as string | undefined;
  }
  const result = envSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues.map(i => `  ${i.path.join('.')}: ${i.message}`).join('\n');
    console.error(`[AETHER] Environment validation failed:\n${issues}`);
    return envSchema.parse({});
  }
  return result.data;
}

export const env = loadEnv();

export function getEnvironment() {
  return env.VITE_AETHER_ENV;
}

export function getRuntimeMode() {
  const e = getEnvironment();
  return e === 'local-mocked' ? 'mocked' as const : 'live' as const;
}

export function isLocalMocked() {
  return env.VITE_AETHER_ENV === 'local-mocked';
}

export function isProduction() {
  return env.VITE_AETHER_ENV === 'production';
}

export function isMockAuthAllowed() {
  return env.VITE_AETHER_ENV === 'local-mocked' || env.VITE_AETHER_ENV === 'local-live';
}
