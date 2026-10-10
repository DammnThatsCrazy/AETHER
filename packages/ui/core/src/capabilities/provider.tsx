/**
 * Capability provider, hook, and route guard.
 *
 * The provider is framework-shared but app-agnostic: each app injects a
 * ``fetchCapabilities`` function (which validates GET /v1/capabilities with the
 * app's own zod schema) and its build identity. Navigation and route guards
 * then read one runtime source, so a signed-in user cannot reach a feature the
 * active profile does not support via a direct URL — the guard renders a
 * truthful state instead.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';

import { resolveDestinationAvailability } from './resolve';
import type {
  BuildInfo,
  Capabilities,
  CapabilityRequirement,
  DestinationAvailability,
} from './types';

interface CapabilityContextValue {
  readonly capabilities: Capabilities | null;
  readonly buildInfo: BuildInfo | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
}

const CapabilityContext = createContext<CapabilityContextValue | null>(null);

export interface CapabilityProviderProps {
  readonly children: ReactNode;
  readonly fetchCapabilities: () => Promise<Capabilities>;
  readonly buildInfo?: BuildInfo | null;
  /** Only fetch once the app is authenticated. Defaults to true. */
  readonly enabled?: boolean;
}

export function CapabilityProvider({
  children,
  fetchCapabilities,
  buildInfo = null,
  enabled = true,
}: CapabilityProviderProps): ReactElement {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchCapabilities()
      .then((c) => {
        if (!cancelled) {
          setCapabilities(c);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, nonce, fetchCapabilities]);

  const value = useMemo<CapabilityContextValue>(
    () => ({
      capabilities,
      buildInfo,
      loading,
      error,
      refresh: () => setNonce((n) => n + 1),
    }),
    [capabilities, buildInfo, loading, error],
  );

  return <CapabilityContext.Provider value={value}>{children}</CapabilityContext.Provider>;
}

export function useCapabilities(): CapabilityContextValue {
  const ctx = useContext(CapabilityContext);
  if (!ctx) {
    throw new Error('useCapabilities must be used within a CapabilityProvider');
  }
  return ctx;
}

export function useBuildInfo(): BuildInfo | null {
  return useContext(CapabilityContext)?.buildInfo ?? null;
}

/** Availability of a requirement, including a ``loading`` state during fetch. */
export function useDestinationAvailability(
  requirement: CapabilityRequirement | undefined,
): DestinationAvailability {
  const { capabilities, loading } = useCapabilities();
  if (loading && !capabilities) return 'loading';
  return resolveDestinationAvailability(capabilities, requirement);
}

function DefaultCapabilityFallback({
  state,
}: {
  readonly state: Exclude<DestinationAvailability, 'available' | 'loading'>;
}): ReactElement {
  const message =
    state === 'not_in_release'
      ? 'This capability is not part of the current release.'
      : state === 'disabled'
        ? 'This capability is turned off for the current deployment.'
        : 'Capability availability could not be verified. Refresh or contact your operator.';
  return (
    <div role="status" style={{ padding: '2rem', textAlign: 'center', opacity: 0.75 }}>
      <p>{message}</p>
    </div>
  );
}

export interface RequireCapabilityProps {
  readonly requirement: CapabilityRequirement;
  readonly children: ReactNode;
  /** Render a custom truthful state instead of the default fallback. */
  readonly fallback?: (state: Exclude<DestinationAvailability, 'available' | 'loading'>) => ReactNode;
  /** Render while capabilities are still loading (defaults to nothing). */
  readonly loadingElement?: ReactNode;
}

/**
 * Route guard: only renders children when the requirement is available for the
 * active profile; otherwise renders a truthful not-in-release / disabled state.
 * Protects direct-URL access, not just navigation visibility.
 */
export function RequireCapability({
  requirement,
  children,
  fallback,
  loadingElement = null,
}: RequireCapabilityProps): ReactElement {
  const state = useDestinationAvailability(requirement);
  if (state === 'loading') return <>{loadingElement}</>;
  if (state === 'available') return <>{children}</>;
  if (fallback) return <>{fallback(state)}</>;
  return <DefaultCapabilityFallback state={state} />;
}
