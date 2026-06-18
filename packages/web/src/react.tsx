// packages/web/src/react.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { AetherSDK } from './index';
import type { ConsentState } from '@aether/shared/consent';

// The singleton is imported lazily so SSR bundles don't instantiate it
let _instance: AetherSDK | null = null;

interface AetherContextValue {
  sdk: AetherSDK;
}

const AetherContext = createContext<AetherContextValue | null>(null);

export interface AetherProviderProps {
  config: Parameters<AetherSDK['init']>[0];
  children: ReactNode;
}

export function AetherProvider({ config, children }: AetherProviderProps) {
  const [sdk, setSdk] = useState<AetherSDK | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    // Dynamic import keeps SSR bundles clean
    import('./index').then(({ default: aether }) => {
      _instance = aether;
      aether.init(config);
      setSdk(aether);
    });
    return () => {
      _instance?.destroy?.();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!sdk) return <>{children}</>;

  return (
    <AetherContext.Provider value={{ sdk }}>
      {children}
    </AetherContext.Provider>
  );
}

export function useAether(): AetherSDK {
  const ctx = useContext(AetherContext);
  if (!ctx) {
    throw new Error('[Aether] useAether() must be used inside <AetherProvider>');
  }
  return ctx.sdk;
}

export interface ResolvedIdentity {
  userId?: string;
  anonymousId?: string;
  traits?: Record<string, unknown>;
}

export function useIdentity(): ResolvedIdentity | null {
  const sdk = useAether();
  const [identity, setIdentity] = useState<ResolvedIdentity | null>(null);

  useEffect(() => {
    const current = sdk.getIdentity?.();
    if (current) setIdentity(current);
    const unsub = sdk.on?.('identify', (event: { properties?: ResolvedIdentity }) => {
      setIdentity(event.properties ?? null);
    });
    return () => unsub?.();
  }, [sdk]);

  return identity;
}

export function useConsentState(): ConsentState | null {
  const sdk = useAether();
  const [state, setState] = useState<ConsentState | null>(null);

  useEffect(() => {
    const current = sdk.consent?.getState?.();
    if (current) setState(current);
    const unsub = sdk.consent?.onUpdate?.(setState);
    return () => unsub?.();
  }, [sdk]);

  return state;
}

export function useScreenOrPageTracking(name?: string): void {
  const sdk = useAether();

  useEffect(() => {
    if (!name) return;
    sdk.pageView?.(name);
  }, [sdk, name]);
}

export function useJourneyResumed(cb: (identity: ResolvedIdentity) => void): void {
  const sdk = useAether();

  useEffect(() => {
    const unsub = sdk.onJourneyResumed?.(cb);
    return () => unsub?.();
  }, [sdk, cb]);
}
