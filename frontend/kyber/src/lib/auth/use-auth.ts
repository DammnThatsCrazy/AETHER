/**
 * Auth hook for Kyber — wraps @auth0/auth0-react's useAuth0 with typed
 * helpers and a consistent interface.
 *
 * Authentication is always supplied by Auth0. Missing configuration is handled
 * by the provider as a startup error rather than an authenticated fallback.
 */
import { useAuth0, type User } from '@auth0/auth0-react';
import { env } from '@kyber/lib/env';

export interface KyberAuthUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly avatarUrl?: string | undefined;
  /** Raw Auth0 User object, available when using real Auth0 */
  readonly raw?: User | undefined;
}

export interface KyberAuth {
  readonly isAuthenticated: boolean;
  readonly isLoading: boolean;
  readonly user: KyberAuthUser | null;
  /** Redirect to Auth0 Universal Login */
  loginWithRedirect: () => Promise<void>;
  /** Log out and redirect to VITE_AUTH0_LOGOUT_URI */
  logout: () => Promise<void>;
  /**
   * Silently obtain a fresh access token with the configured audience.
   * Throws if not authenticated or token fetch fails.
   */
  getAccessToken: () => Promise<string>;
}

function mapAuth0User(user: User | undefined): KyberAuthUser | null {
  if (!user) return null;
  return {
    id: user.sub ?? '',
    email: user.email ?? '',
    displayName: user.name ?? user.email ?? '',
    avatarUrl: user.picture,
    raw: user,
  };
}

/**
 * useAuth — unified auth hook for Kyber.
 */
export function useAuth(): KyberAuth {
  const auth0 = useAuth0();

  return {
    isAuthenticated: auth0.isAuthenticated,
    isLoading: auth0.isLoading,
    user: mapAuth0User(auth0.user),
    loginWithRedirect: () => auth0.loginWithRedirect(),
    logout: () =>
      auth0.logout({
        logoutParams: {
          returnTo: env.VITE_AUTH0_LOGOUT_URI ?? window.location.origin,
        },
      }),
    getAccessToken: () =>
      auth0.getAccessTokenSilently(
        env.VITE_AUTH0_AUDIENCE
          ? { authorizationParams: { audience: env.VITE_AUTH0_AUDIENCE } }
          : undefined,
      ),
  };
}
