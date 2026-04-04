import { createContext, useContext, useCallback, useReducer, useEffect, type ReactNode } from 'react';
import type { AuthState, ShikiUser, ShikiRole, AuthTokens } from '@shiki/types';
import { isMockAuthAllowed, isLocalMocked } from '@shiki/lib/env';
import { MOCK_USERS } from '@shiki/fixtures/auth';

interface AuthContextValue extends AuthState {
  login: () => Promise<void>;
  logout: () => Promise<void>;
  switchMockUser: (role: ShikiRole) => void;
}

type AuthAction =
  | { type: 'AUTH_START' }
  | { type: 'AUTH_SUCCESS'; user: ShikiUser; tokens: AuthTokens }
  | { type: 'AUTH_FAILURE'; error: string | null }
  | { type: 'AUTH_LOGOUT' }
  | { type: 'MOCK_LOGIN'; user: ShikiUser };

function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'AUTH_START':
      return { ...state, isLoading: true, error: null };
    case 'AUTH_SUCCESS':
      return { isAuthenticated: true, user: action.user, isLoading: false, error: null };
    case 'AUTH_FAILURE':
      return { isAuthenticated: false, user: null, isLoading: false, error: action.error };
    case 'AUTH_LOGOUT':
      return { isAuthenticated: false, user: null, isLoading: false, error: null };
    case 'MOCK_LOGIN':
      return { isAuthenticated: true, user: action.user, isLoading: false, error: null };
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Token storage (in-memory only, never persisted to localStorage in production)
let currentTokens: AuthTokens | null = null;

export function getAccessToken(): string | null {
  return currentTokens?.accessToken ?? null;
}

function generatePKCEVerifier(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

async function generatePKCEChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function mapClaimsToRole(groups: readonly string[]): ShikiRole {
  if (groups.includes('shiki_executive_operator') || groups.includes('executive')) {
    return 'shiki_executive_operator';
  }
  if (groups.includes('shiki_engineering_command') || groups.includes('engineering')) {
    return 'shiki_engineering_command';
  }
  if (groups.includes('shiki_specialist_operator') || groups.includes('specialist')) {
    return 'shiki_specialist_operator';
  }
  return 'shiki_observer';
}

export function AuthProvider({ children }: { readonly children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, {
    isAuthenticated: false,
    user: null,
    isLoading: true,
    error: null,
  });

  useEffect(() => {
    // Auto-login in local mocked mode
    if (isLocalMocked()) {
      const defaultUser = MOCK_USERS.shiki_engineering_command;
      dispatch({ type: 'MOCK_LOGIN', user: defaultUser });
      return;
    }

    // Check for OIDC callback
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (code) {
      handleOIDCCallback(code).catch(err => {
        dispatch({ type: 'AUTH_FAILURE', error: String(err) });
      });
    } else {
      // Check existing session
      checkSession();
    }
  }, []);

  async function handleOIDCCallback(code: string): Promise<void> {
    dispatch({ type: 'AUTH_START' });
    try {
      const verifier = sessionStorage.getItem('shiki_pkce_verifier');
      if (!verifier) throw new Error('Missing PKCE verifier');

      // Exchange code for tokens via backend
      const response = await fetch('/api/v1/auth/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, code_verifier: verifier }),
      });

      if (!response.ok) throw new Error('Token exchange failed');

      const tokens = (await response.json()) as AuthTokens;
      currentTokens = tokens;
      sessionStorage.removeItem('shiki_pkce_verifier');

      // Decode ID token claims
      const claims = JSON.parse(atob(tokens.idToken.split('.')[1] ?? '{}')) as Record<string, unknown>;
      const groups = (claims['groups'] as string[] | undefined) ?? [];
      const user: ShikiUser = {
        id: String(claims['sub'] ?? ''),
        email: String(claims['email'] ?? ''),
        displayName: String(claims['name'] ?? claims['email'] ?? ''),
        role: mapClaimsToRole(groups),
        groups,
        avatarUrl: typeof claims['picture'] === 'string' ? claims['picture'] : undefined,
      };

      dispatch({ type: 'AUTH_SUCCESS', user, tokens });

      // Clean URL
      window.history.replaceState({}, '', window.location.pathname);
    } catch (err) {
      dispatch({ type: 'AUTH_FAILURE', error: err instanceof Error ? err.message : 'Auth failed' });
    }
  }

  function checkSession(): void {
    // If we have tokens in memory and they're not expired, restore session
    if (currentTokens && currentTokens.expiresAt > Date.now() / 1000) {
      // Session exists but we'd need to decode — for now mark as needing login
    }
    dispatch({ type: 'AUTH_FAILURE', error: null });
  }

  const login = useCallback(async () => {
    if (isMockAuthAllowed() && !currentTokens) {
      const defaultUser = MOCK_USERS.shiki_engineering_command;
      dispatch({ type: 'MOCK_LOGIN', user: defaultUser });
      return;
    }

    dispatch({ type: 'AUTH_START' });

    const { env } = await import('@shiki/lib/env');
    const authority = env.VITE_OIDC_AUTHORITY;
    const clientId = env.VITE_OIDC_CLIENT_ID;
    const redirectUri = env.VITE_OIDC_REDIRECT_URI;
    const scope = env.VITE_OIDC_SCOPE;

    if (!authority || !clientId || !redirectUri) {
      dispatch({ type: 'AUTH_FAILURE', error: 'OIDC not configured' });
      return;
    }

    const verifier = generatePKCEVerifier();
    const challenge = await generatePKCEChallenge(verifier);
    sessionStorage.setItem('shiki_pkce_verifier', verifier);

    const authUrl = new URL(`${authority}/authorize`);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('client_id', clientId);
    authUrl.searchParams.set('redirect_uri', redirectUri);
    authUrl.searchParams.set('scope', scope);
    authUrl.searchParams.set('code_challenge', challenge);
    authUrl.searchParams.set('code_challenge_method', 'S256');

    window.location.href = authUrl.toString();
  }, []);

  const logout = useCallback(async () => {
    currentTokens = null;
    dispatch({ type: 'AUTH_LOGOUT' });

    if (!isMockAuthAllowed()) {
      const { env } = await import('@shiki/lib/env');
      if (env.VITE_OIDC_AUTHORITY) {
        window.location.href = `${env.VITE_OIDC_AUTHORITY}/logout?post_logout_redirect_uri=${encodeURIComponent(window.location.origin)}`;
        return;
      }
    }
  }, []);

  const switchMockUser = useCallback((role: ShikiRole) => {
    if (!isMockAuthAllowed()) return;
    const user = MOCK_USERS[role];
    dispatch({ type: 'MOCK_LOGIN', user });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, switchMockUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
