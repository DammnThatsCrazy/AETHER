/**
 * Auth hook for Aether customer app — wraps @auth0/auth0-react's useAuth0
 * with typed helpers and a consistent interface.
 */
import { useAuth0, type User } from '@auth0/auth0-react';
import { env } from '@aether-app/lib/env';

export interface AetherAuthUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly avatarUrl?: string | undefined;
  /** Raw Auth0 User object, available when using real Auth0 */
  readonly raw?: User | undefined;
}

export interface AetherAuth {
  readonly isAuthenticated: boolean;
  readonly isLoading: boolean;
  readonly user: AetherAuthUser | null;
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

function mapAuth0User(user: User | undefined): AetherAuthUser | null {
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
 * Auth0-backed auth hook. Local backend authentication uses the separate
 * features/auth provider and never enters this hook through a mock branch.
 */
export function useAuth(): AetherAuth {
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
