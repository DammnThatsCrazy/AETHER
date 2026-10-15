import { env, getEnvironment, isProduction } from './config';

export interface ValidationResult {
  readonly variable: string;
  readonly required: boolean;
  readonly present: boolean;
  readonly valid: boolean;
  readonly message?: string | undefined;
}

export function validateEnvironment(): ValidationResult[] {
  const results: ValidationResult[] = [];
  const environment = getEnvironment();

  results.push({
    variable: 'VITE_AETHER_ENV',
    required: true,
    present: true,
    valid: true,
  });

  const authRequired = isProduction() || environment === 'staging';
  const oidcComplete = !!env.VITE_OIDC_AUTHORITY && !!env.VITE_OIDC_CLIENT_ID && !!env.VITE_OIDC_REDIRECT_URI;
  const auth0Complete = !!env.VITE_AUTH0_DOMAIN && !!env.VITE_AUTH0_CLIENT_ID && !!env.VITE_AUTH0_REDIRECT_URI;
  const authComplete = oidcComplete || auth0Complete;
  results.push({
    variable: 'AUTH_CONFIGURATION',
    required: authRequired,
    present: authComplete,
    valid: authRequired ? authComplete : true,
    message: authRequired && !authComplete ? 'Complete OIDC or Auth0 configuration required for non-local environments' : undefined,
  });

  results.push({
    variable: 'VITE_API_BASE_URL',
    required: true,
    present: !!env.VITE_API_BASE_URL,
    valid: true,
  });

  return results;
}

export function getStartupValidationSummary(): { ok: boolean; results: ValidationResult[] } {
  const results = validateEnvironment();
  const ok = results.every(r => r.valid);
  return { ok, results };
}
