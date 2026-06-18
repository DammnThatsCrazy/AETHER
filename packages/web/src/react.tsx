// packages/web/src/react.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { AetherSDKInterface } from '@aether/web';
import type { ConsentState } from '@aether/shared/consent';

// The singleton is imported lazily so SSR bundles don't instantiate it.
// '@aether/web' is marked external so this import resolves correctly from dist/react.js.
let _instance: AetherSDKInterface | null = null;

interface AetherContextValue {
  sdk: AetherSDKInterface;
}

const AetherContext = createContext<AetherContextValue | null>(null);

export interface AetherProviderProps {
  config: Parameters<AetherSDKInterface['init']>[0];
  children: ReactNode;
}

export function AetherProvider({ config, children }: AetherProviderProps) {
  const [sdk, setSdk] = useState<AetherSDKInterface | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    // Import via package name so the resolved path is dist/aether.esm.js, not dist/index.js.
    import('@aether/web').then(({ default: aether }) => {
      _instance = aether;
      aether.init(config);
      setSdk(aether);
    });
    return () => {
      _instance?.destroy?.();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Do not render children until the SDK is ready — hooks that call useAether() would throw
  // if rendered with a null context, producing a confusing error before the async import resolves.
  if (!sdk) return null;

  return (
    <AetherContext.Provider value={{ sdk }}>
      {children}
    </AetherContext.Provider>
  );
}

export function useAether(): AetherSDKInterface {
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
    if (current) setIdentity(current as ResolvedIdentity);
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
