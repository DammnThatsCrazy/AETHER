/**
 * Kyber authentication context — backend-authoritative, token-free.
 *
 * What this deliberately does NOT do (and must never do again):
 *   - generate PKCE verifiers/challenges in the browser
 *   - keep access/ID/refresh tokens in a module variable or storage
 *   - decode a JWT (`atob(idToken.split('.')[1])`) to learn who the user is
 *   - map a `groups` claim to a role
 *
 * Instead: the session lives in a server-side `__Host-kyber_session` HttpOnly
 * cookie. This provider asks the backend two questions — `GET /v1/kyber/me`
 * and `GET /v1/kyber/auth/session` — and renders whatever the backend says.
 * Identity, roles, capabilities, action ceilings and expiries are all server
 * facts. If the backend says 401 we are logged out immediately, no grace.
 *
 * Freshness: the session is refetched on window focus, on `visibilitychange`,
 * and on a timer, so a session that expires or gets risk-limited server-side
 * shows up in the UI without a manual reload.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { KyberPrincipalView, KyberSessionView } from '@kyber/types';
import { KyberAuthError, SESSION_EXPIRED_EVENT, describeAuthError } from '@kyber/lib/auth';
import { endSession, fetchPrincipal, fetchSession, startLogin } from './session-client';

export type KyberAuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'error';

export interface KyberAuthContextValue {
  readonly status: KyberAuthStatus;
  readonly principal: KyberPrincipalView | null;
  readonly session: KyberSessionView | null;
  readonly isAuthenticated: boolean;
  readonly isLoading: boolean;
  readonly error: string | null;
  /** Full-page navigation into the backend-driven login redirect. */
  readonly login: (returnTo?: string) => void;
  readonly logout: () => Promise<void>;
  /** Force an immediate re-read of principal + session. */
  readonly refresh: () => Promise<void>;
  readonly lastSyncedAt: number | null;
}

const KyberAuthContext = createContext<KyberAuthContextValue | null>(null);

/** Default poll cadence for session freshness. */
export const SESSION_POLL_INTERVAL_MS = 60_000;

interface AuthProviderProps {
  readonly children: ReactNode;
  readonly pollIntervalMs?: number | undefined;
}

export function AuthProvider({ children, pollIntervalMs }: AuthProviderProps) {
  const [principal, setPrincipal] = useState<KyberPrincipalView | null>(null);
  const [session, setSession] = useState<KyberSessionView | null>(null);
  const [status, setStatus] = useState<KyberAuthStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);

  const mountedRef = useRef(true);
  const inFlightRef = useRef<Promise<void> | null>(null);
  const interval = pollIntervalMs ?? SESSION_POLL_INTERVAL_MS;

  const applyLoggedOut = useCallback(() => {
    if (!mountedRef.current) return;
    setPrincipal(null);
    setSession(null);
    setError(null);
    setStatus('unauthenticated');
  }, []);

  const sync = useCallback(async (): Promise<void> => {
    const existing = inFlightRef.current;
    if (existing !== null) return existing;

    const run = (async () => {
      try {
        // The principal read is the authority. The session read is
        // supplementary detail (risk reasons, step-up flags); a non-401 failure
        // there must not log the operator out.
        const nextPrincipal = await fetchPrincipal();
        let nextSession: KyberSessionView | null = null;
        try {
          nextSession = await fetchSession();
        } catch (sessionErr) {
          if (sessionErr instanceof KyberAuthError && sessionErr.isUnauthenticated) {
            applyLoggedOut();
            return;
          }
          nextSession = null;
        }
        if (!mountedRef.current) return;
        setPrincipal(nextPrincipal);
        setSession(nextSession);
        setError(null);
        setStatus('authenticated');
        setLastSyncedAt(Date.now());
      } catch (err) {
        if (!mountedRef.current) return;
        if (err instanceof KyberAuthError && err.isUnauthenticated) {
          applyLoggedOut();
          return;
        }
        setPrincipal(null);
        setSession(null);
        setError(describeAuthError(err));
        setStatus('error');
      }
    })();

    inFlightRef.current = run;
    try {
      await run;
    } finally {
      inFlightRef.current = null;
    }
  }, [applyLoggedOut]);

  // Initial read.
  useEffect(() => {
    mountedRef.current = true;
    void sync();
    return () => {
      mountedRef.current = false;
    };
  }, [sync]);

  // Any 401 observed anywhere in the app is an immediate logout.
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const onExpired = () => applyLoggedOut();
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [applyLoggedOut]);

  // Refresh on focus / tab visibility so a server-side change is picked up the
  // moment the operator comes back to the tab.
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const onFocus = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      void sync();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [sync]);

  // Timer-based freshness.
  useEffect(() => {
    if (interval <= 0) return undefined;
    const timer = setInterval(() => {
      void sync();
    }, interval);
    return () => clearInterval(timer);
  }, [interval, sync]);

  const login = useCallback((returnTo?: string) => {
    const fallback = typeof window === 'undefined' ? undefined : window.location.pathname;
    startLogin(returnTo ?? fallback);
  }, []);

  const logout = useCallback(async () => {
    try {
      await endSession();
    } catch {
      // A failed logout still drops local state; the cookie is the backend's
      // to clear and a stale cookie will 401 on the next call anyway.
    }
    applyLoggedOut();
  }, [applyLoggedOut]);

  const value = useMemo<KyberAuthContextValue>(
    () => ({
      status,
      principal,
      session,
      isAuthenticated: status === 'authenticated' && principal !== null,
      isLoading: status === 'loading',
      error,
      login,
      logout,
      refresh: sync,
      lastSyncedAt,
    }),
    [status, principal, session, error, login, logout, sync, lastSyncedAt],
  );

  return <KyberAuthContext.Provider value={value}>{children}</KyberAuthContext.Provider>;
}

export function useAuth(): KyberAuthContextValue {
  const ctx = useContext(KyberAuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

/** Non-throwing variant for components that may render outside the provider. */
export function useOptionalAuth(): KyberAuthContextValue | null {
  return useContext(KyberAuthContext);
}
