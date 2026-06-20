/**
 * Auth0 provider wrapper for Aether customer app.
 *
 * When Auth0 credentials are absent (VITE_AUTH0_DOMAIN / VITE_AUTH0_CLIENT_ID unset),
 * this is a no-op passthrough for all non-production environments (local-mocked,
 * local-live, staging). Production fails closed with a startup error.
 * The existing AuthProvider in features/auth handles authentication in those envs.
 *
 * In all other environments, this wraps the app in Auth0Provider from
 * @auth0/auth0-react and enforces that required vars are present.
 */
import type { ReactNode } from 'react';
import { Auth0Provider } from '@auth0/auth0-react';
import { env, isLocalMocked, isProduction } from '@aether-app/lib/env';

interface AetherAuth0ProviderProps {
  readonly children: ReactNode;
}

export function AetherAuth0Provider({ children }: AetherAuth0ProviderProps) {
  const domain = env.VITE_AUTH0_DOMAIN;
  const clientId = env.VITE_AUTH0_CLIENT_ID;

  // In local-mocked mode with no Auth0 config, skip the provider entirely.
  // The existing AuthProvider in features/auth handles mock authentication.
  if (!domain || !clientId) {
    if (isProduction()) {
      // Production without credentials — fail closed with a clear error at startup.
      throw new Error(
        `[Aether] Auth0 is not configured. ` +
        `Set VITE_AUTH0_DOMAIN and VITE_AUTH0_CLIENT_ID in your environment. ` +
        `Current VITE_AETHER_ENV=${env.VITE_AETHER_ENV}`,
      );
    }
    // local-mocked, local-live, staging: skip Auth0 wrapper — the existing
    // AuthProvider in features/auth handles authentication for these envs.
    return <>{children}</>;
  }

  const redirectUri =
    env.VITE_AUTH0_REDIRECT_URI ??
    `${window.location.origin}/callback`;

  return (
    <Auth0Provider
      domain={domain}
      clientId={clientId}
      authorizationParams={{
        redirect_uri: redirectUri,
        audience: env.VITE_AUTH0_AUDIENCE,
        scope: 'openid profile email',
      }}
    >
      {children}
    </Auth0Provider>
  );
}
