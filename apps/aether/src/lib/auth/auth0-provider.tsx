/**
 * Auth0 provider wrapper for Aether customer app.
 *
 * In local-mocked mode (VITE_AUTH0_DOMAIN not set), this is a no-op passthrough
 * so local dev works without Auth0 credentials. The existing mock AuthProvider
 * handles authentication in that case.
 *
 * In all other environments, this wraps the app in Auth0Provider from
 * @auth0/auth0-react and enforces that required vars are present.
 */
import type { ReactNode } from 'react';
import { Auth0Provider } from '@auth0/auth0-react';
import { env, isLocalMocked } from '@aether-app/lib/env';

interface AetherAuth0ProviderProps {
  readonly children: ReactNode;
}

export function AetherAuth0Provider({ children }: AetherAuth0ProviderProps) {
  const domain = env.VITE_AUTH0_DOMAIN;
  const clientId = env.VITE_AUTH0_CLIENT_ID;

  // In local-mocked mode with no Auth0 config, skip the provider entirely.
  // The existing AuthProvider in features/auth handles mock authentication.
  if (!domain || !clientId) {
    if (!isLocalMocked()) {
      // Non-local env without credentials — surface a clear error at startup.
      throw new Error(
        `[Aether] Auth0 is not configured. ` +
        `Set VITE_AUTH0_DOMAIN and VITE_AUTH0_CLIENT_ID in your environment. ` +
        `Current VITE_AETHER_ENV=${env.VITE_AETHER_ENV}`,
      );
    }
    // Local-mocked: silently skip Auth0 wrapper.
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
