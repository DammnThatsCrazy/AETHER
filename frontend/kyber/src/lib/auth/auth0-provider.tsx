/**
 * Auth0 provider wrapper for Kyber.
 *
 * Authentication configuration is required in every runtime environment.
 * Missing values fail startup instead of activating an alternate auth path.
 */
import type { ReactNode } from 'react';
import { Auth0Provider } from '@auth0/auth0-react';
import { env } from '@kyber/lib/env';

interface AetherAuth0ProviderProps {
  readonly children: ReactNode;
}

export function AetherAuth0Provider({ children }: AetherAuth0ProviderProps) {
  const domain = env.VITE_AUTH0_DOMAIN;
  const clientId = env.VITE_AUTH0_CLIENT_ID;

  if (!domain || !clientId) {
    throw new Error(
      `[Kyber] Auth0 is not configured. ` +
      `Set VITE_AUTH0_DOMAIN and VITE_AUTH0_CLIENT_ID in your environment. ` +
      `Current VITE_KYBER_ENV=${env.VITE_KYBER_ENV}`,
    );
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
        scope: 'openid profile email groups',
      }}
    >
      {children}
    </Auth0Provider>
  );
}
