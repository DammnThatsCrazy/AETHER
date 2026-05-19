/**
 * Auth hook for Aether customer app — wraps @auth0/auth0-react's useAuth0
 * with typed helpers and a consistent interface.
 *
 * In local-mocked mode (Auth0 not configured), falls back to the existing
 * mock auth context via features/auth so the interface is always the same.
 */
import { useAuth0, type User } from '@auth0/auth0-react';
import { env, isLocalMocked } from '@aether-app/lib/env';
import { useAuth as useMockAuth } from '@aether-app/features/auth';

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

// Determined at module-load time — won't change during a session.
const USE_MOCK = isLocalMocked() && !env.VITE_AUTH0_DOMAIN;

/**
 * useAuth — unified auth hook for Aether.
 *
 * Returns the same interface regardless of whether Auth0 is configured.
 * In local-mocked mode (no VITE_AUTH0_DOMAIN), returns the mock auth state.
 * In all other modes, returns the real Auth0 state.
 *
 * Both underlying hooks are always called (hooks must not be conditional),
 * but only the active branch's return value is used.
 */
export function useAuth(): AetherAuth {
  // Always call both — hook rules require unconditional calls.
  const mock = useMockAuth();
  const auth0 = useAuth0();

  if (USE_MOCK) {
    const mockUser: AetherAuthUser | null = mock.user
      ? {
          id: mock.user.id,
          email: mock.user.email,
          displayName: mock.user.displayName,
          avatarUrl: mock.user.avatarUrl,
        }
      : null;

    return {
      isAuthenticated: mock.isAuthenticated,
      isLoading: mock.isLoading,
      user: mockUser,
      loginWithRedirect: () => mock.login(),
      logout: () => mock.logout(),
      getAccessToken: () => Promise.resolve('mock-access-token'),
    };
  }

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
