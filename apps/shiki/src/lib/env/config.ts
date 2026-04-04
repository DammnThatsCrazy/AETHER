import { z } from 'zod';

const envSchema = z.object({
  VITE_SHIKI_ENV: z.enum(['local-mocked', 'local-live', 'staging', 'production']).default('local-mocked'),
  VITE_API_BASE_URL: z.string().url().default('http://localhost:8000'),
  VITE_WS_BASE_URL: z.string().default('ws://localhost:8000'),
  VITE_GRAPHQL_URL: z.string().url().default('http://localhost:8000/v1/analytics/graphql'),
  VITE_OIDC_AUTHORITY: z.string().url().optional(),
  VITE_OIDC_CLIENT_ID: z.string().optional(),
  VITE_OIDC_REDIRECT_URI: z.string().url().optional(),
  VITE_OIDC_SCOPE: z.string().default('openid profile email groups'),
  VITE_SLACK_WEBHOOK_URL: z.string().url().optional(),
  VITE_AUTOMATION_POSTURE: z.enum(['conservative', 'balanced', 'aggressive']).default('conservative'),
  VITE_FEATURE_FLAGS: z.string().default('{}'),
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
    console.error(`[SHIKI] Environment validation failed:\n${issues}`);
    // Fall back to defaults in local mode
    return envSchema.parse({});
  }
  return result.data;
}

export const env = loadEnv();

export function getEnvironment() {
  return env.VITE_SHIKI_ENV;
}

export function getRuntimeMode() {
  const e = getEnvironment();
  return e === 'local-mocked' ? 'mocked' as const : 'live' as const;
}

export function isProduction() {
  return env.VITE_SHIKI_ENV === 'production';
}

export function isLocalMocked() {
  return env.VITE_SHIKI_ENV === 'local-mocked';
}

export function isMockAuthAllowed() {
  return env.VITE_SHIKI_ENV === 'local-mocked' || env.VITE_SHIKI_ENV === 'local-live';
}
