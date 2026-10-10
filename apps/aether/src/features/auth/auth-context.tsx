import { createContext, useContext, useCallback, useReducer, useEffect, useRef, type ReactNode } from 'react';
import type { AuthState, AetherUser, AuthTokens } from '@aether-app/types';
import type { HumanSessionGrant } from './grant';

/** Legacy reusable API-key credential (trust-plane flag off on the backend). */
export const SESSION_KEY = 'aether_session_key';
/** Trust-plane session token ("sess_...") — revocable, server-tracked. */
export const SESSION_TOKEN_KEY = 'aether_session_token';
/** Absolute expiry (ISO 8601) of the stored trust-plane session. */
export const SESSION_EXPIRY_KEY = 'aether_session_expires_at';

// Fallback session lifetime when the grant omits absolute_expires_at —
// mirrors the backend default of a 12-hour absolute session expiry.
const SESSION_FALLBACK_TTL_S = 12 * 60 * 60;

interface AuthContextValue extends AuthState {
  login: () => Promise<void>;
  logout: () => Promise<void>;
  apiKeyLogin: (apiKey: string) => Promise<void>;
  /** Authenticate with a trust-plane session grant (never a reusable key). */
  sessionLogin: (session: HumanSessionGrant) => Promise<void>;
}

type AuthAction =
  | { type: 'AUTH_START' }
  | { type: 'AUTH_SUCCESS'; user: AetherUser; tokens: AuthTokens }
  | { type: 'AUTH_FAILURE'; error: string | null }
  | { type: 'AUTH_LOGOUT' };

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
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

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

function decodeUser(tokens: AuthTokens): AetherUser {
  const claims = JSON.parse(atob(tokens.idToken.split('.')[1] ?? '{}')) as Record<string, unknown>;
  return {
    id: String(claims['sub'] ?? ''),
    email: String(claims['email'] ?? ''),
    displayName: String(claims['name'] ?? claims['email'] ?? ''),
    avatarUrl: typeof claims['picture'] === 'string' ? claims['picture'] : undefined,
  };
}

// How many seconds before expiry to trigger a silent refresh.
const REFRESH_SKEW_S = 300;

function sessionExpiryEpochS(iso: string | null | undefined): number {
  if (iso) {
    const parsed = Date.parse(iso);
    if (!Number.isNaN(parsed)) return parsed / 1000;
  }
  return Date.now() / 1000 + SESSION_FALLBACK_TTL_S;
}

/**
 * Restore a persisted credential, preferring the trust-plane session token
 * over a legacy API key. Expired session tokens are cleared, never reused.
 */
function restoreStoredCredential(): AuthTokens | null {
  const sessionToken = sessionStorage.getItem(SESSION_TOKEN_KEY);
  if (sessionToken) {
    const storedExpiry = sessionStorage.getItem(SESSION_EXPIRY_KEY);
    const parsedExpiry = storedExpiry ? Date.parse(storedExpiry) / 1000 : Number.NaN;
    if (Number.isFinite(parsedExpiry) && parsedExpiry > Date.now() / 1000) {
      const expiresAt = parsedExpiry;
      return { accessToken: sessionToken, idToken: '', refreshToken: undefined, expiresAt };
    }
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    sessionStorage.removeItem(SESSION_EXPIRY_KEY);
  }
  const storedKey = sessionStorage.getItem(SESSION_KEY);
  if (storedKey) {
    return { accessToken: storedKey, idToken: '', refreshToken: undefined, expiresAt: Date.now() / 1000 + 86400 };
  }
  return null;
}

interface BackendProfile {
  readonly tenant_id: string;
  readonly name: string;
  readonly contact_email: string;
}

function profileUser(profile: BackendProfile): AetherUser {
  return {
    id: profile.tenant_id,
    email: profile.contact_email,
    displayName: profile.name || profile.contact_email || profile.tenant_id,
  };
}

export function AuthProvider({ children }: { readonly children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, {
    isAuthenticated: false,
    user: null,
    isLoading: true,
    error: null,
  });

  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scheduleRefresh(tokens: AuthTokens): void {
    if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current);
    const msUntilRefresh = (tokens.expiresAt - REFRESH_SKEW_S) * 1000 - Date.now();
    if (msUntilRefresh <= 0) {
      void silentRefresh();
      return;
    }
    refreshTimerRef.current = setTimeout(() => { void silentRefresh(); }, msUntilRefresh);
  }

  async function silentRefresh(): Promise<void> {
    if (!currentTokens?.refreshToken) {
      currentTokens = null;
      dispatch({ type: 'AUTH_LOGOUT' });
      return;
    }
    try {
      const response = await fetch('/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentTokens.refreshToken }),
      });
      if (!response.ok) throw new Error('Refresh failed');
      const tokens = (await response.json()) as AuthTokens;
      currentTokens = tokens;
      scheduleRefresh(tokens);
      dispatch({ type: 'AUTH_SUCCESS', user: decodeUser(tokens), tokens });
    } catch {
      currentTokens = null;
      if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current);
      dispatch({ type: 'AUTH_LOGOUT' });
    }
  }

  async function verifyCredential(tokens: AuthTokens): Promise<void> {
    currentTokens = tokens;
    try {
      const { api } = await import('@aether-app/lib/api/endpoints');
      const profile = await api.me.profile();
      if (!profile.tenant_id) throw new Error('Authenticated profile omitted tenant identity');
      dispatch({ type: 'AUTH_SUCCESS', user: profileUser(profile), tokens });
    } catch (err) {
      currentTokens = null;
      sessionStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_TOKEN_KEY);
      sessionStorage.removeItem(SESSION_EXPIRY_KEY);
      dispatch({
        type: 'AUTH_FAILURE',
        error: err instanceof Error ? err.message : 'Stored credential validation failed',
      });
      throw err;
    }
  }

  useEffect(() => {
    // Restore a persisted credential — trust-plane session token first,
    // then the legacy API key. An opaque credential is not authentication
    // evidence by itself: validate it against the backend before granting
    // access or constructing an identity.
    const restored = restoreStoredCredential();
    if (restored) {
      void verifyCredential(restored).catch(() => undefined);
    } else {
      const params = new URLSearchParams(window.location.search);
      const code = params.get('code');
      if (code) {
        handleOIDCCallback(code).catch(err => {
          dispatch({ type: 'AUTH_FAILURE', error: String(err) });
        });
      } else {
        checkSession();
      }
    }

    return () => {
      if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  async function handleOIDCCallback(code: string): Promise<void> {
    dispatch({ type: 'AUTH_START' });
    try {
      const verifier = sessionStorage.getItem('aether_pkce_verifier');
      if (!verifier) throw new Error('Missing PKCE verifier');

      const response = await fetch('/v1/auth/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, code_verifier: verifier }),
      });

      if (!response.ok) throw new Error('Token exchange failed');

      const tokens = (await response.json()) as AuthTokens;
      currentTokens = tokens;
      sessionStorage.removeItem('aether_pkce_verifier');

      scheduleRefresh(tokens);
      dispatch({ type: 'AUTH_SUCCESS', user: decodeUser(tokens), tokens });
      window.history.replaceState({}, '', window.location.pathname);
    } catch (err) {
      dispatch({ type: 'AUTH_FAILURE', error: err instanceof Error ? err.message : 'Auth failed' });
    }
  }

  function checkSession(): void {
    if (currentTokens && currentTokens.expiresAt > Date.now() / 1000) {
      try {
        dispatch({ type: 'AUTH_SUCCESS', user: decodeUser(currentTokens), tokens: currentTokens });
        scheduleRefresh(currentTokens);
        return;
      } catch {
        // Malformed token — fall through to login required
      }
    }
    currentTokens = null;
    dispatch({ type: 'AUTH_FAILURE', error: null });
  }

  const login = useCallback(async () => {
    dispatch({ type: 'AUTH_START' });

    const { env } = await import('@aether-app/lib/env');
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
    sessionStorage.setItem('aether_pkce_verifier', verifier);

    const authUrl = new URL(`${authority}/authorize`);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('client_id', clientId);
    authUrl.searchParams.set('redirect_uri', redirectUri);
    authUrl.searchParams.set('scope', scope);
    authUrl.searchParams.set('code_challenge', challenge);
    authUrl.searchParams.set('code_challenge_method', 'S256');

    window.location.href = authUrl.toString();
  }, []);

  const apiKeyLogin = useCallback(async (apiKey: string) => {
    sessionStorage.setItem(SESSION_KEY, apiKey);
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    sessionStorage.removeItem(SESSION_EXPIRY_KEY);
    const tokens = {
      accessToken: apiKey,
      idToken: '',
      refreshToken: undefined,
      expiresAt: Date.now() / 1000 + 86400,
    };
    await verifyCredential(tokens);
  }, []);

  const sessionLogin = useCallback(async (session: HumanSessionGrant) => {
    const expiresAt = sessionExpiryEpochS(session.absolute_expires_at);
    sessionStorage.setItem(SESSION_TOKEN_KEY, session.token);
    sessionStorage.setItem(SESSION_EXPIRY_KEY, new Date(expiresAt * 1000).toISOString());
    // A trust-plane session supersedes any legacy key credential.
    sessionStorage.removeItem(SESSION_KEY);
    const tokens = {
      accessToken: session.token,
      idToken: '',
      refreshToken: undefined,
      expiresAt,
    };
    await verifyCredential(tokens);
  }, []);

  const logout = useCallback(async () => {
    currentTokens = null;
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    sessionStorage.removeItem(SESSION_EXPIRY_KEY);
    if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current);
    dispatch({ type: 'AUTH_LOGOUT' });

    const { env } = await import('@aether-app/lib/env');
    if (env.VITE_OIDC_AUTHORITY) {
      window.location.href = `${env.VITE_OIDC_AUTHORITY}/logout?post_logout_redirect_uri=${encodeURIComponent(window.location.origin)}`;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, apiKeyLogin, sessionLogin }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
