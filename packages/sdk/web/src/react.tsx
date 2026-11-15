// packages/sdk/web/src/react.tsx
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { AetherSDKInterface } from '@olympuslabs/aether-web';
import type { ConsentState } from '@olympuslabs/aether-shared/consent';

// The singleton is imported lazily so SSR bundles don't instantiate it.
// '@olympuslabs/aether-web' is marked external so this import resolves correctly from dist/react.js.
let _instance: AetherSDKInterface | null = null;

// One shared import for every provider mount: Strict Mode's mount-unmount-mount
// and restarts reuse the same module promise instead of starting new loads.
// Import via package name so the resolved path is dist/aether.esm.js, not dist/index.js.
let sdkModule: Promise<typeof import('@olympuslabs/aether-web')> | null = null;
function loadSdk(): Promise<typeof import('@olympuslabs/aether-web')> {
  sdkModule ??= import('@olympuslabs/aether-web').catch((error: unknown) => {
    sdkModule = null; // allow a later mount to retry a failed load
    throw error;
  });
  return sdkModule;
}

interface AetherContextValue {
  sdk: AetherSDKInterface;
}

const AetherContext = createContext<AetherContextValue | null>(null);

export interface AetherProviderProps {
  /**
   * SDK config. A change to `apiKey`, `siteId`, `endpoint` or `environment`
   * restarts the SDK; other options are applied once, at init.
   */
  config: Parameters<AetherSDKInterface['init']>[0];
  children: ReactNode;
}

type AetherProviderConfig = Parameters<AetherSDKInterface['init']>[0];

/**
 * Config keys that identify *which* install the SDK reports as. A change to
 * any of them restarts the SDK (destroy, then init with the new config). Every
 * other option is read once at init: changing it later has no effect, and a
 * development-mode warning says so. Keying on these values (not on object
 * identity) means the common inline `config={{ ... }}` does not restart the
 * SDK on every render.
 */
const RESTART_KEYS = ['apiKey', 'siteId', 'endpoint', 'environment'] as const;

function restartKey(config: AetherProviderConfig): string {
  return JSON.stringify(RESTART_KEYS.map((key) => config[key] ?? null));
}

function isDevelopment(): boolean {
  const env = (globalThis as { process?: { env?: { NODE_ENV?: string } } }).process?.env?.NODE_ENV;
  return env !== undefined && env !== 'production';
}

export function AetherProvider({ config, children }: AetherProviderProps) {
  const [sdk, setSdk] = useState<AetherSDKInterface | null>(null);
  // The latest config, read when the (async) init actually runs.
  const configRef = useRef(config);
  configRef.current = config;
  // The config the running SDK was initialized with, for the dev warning.
  const initializedWith = useRef<AetherProviderConfig | null>(null);
  const warned = useRef(new Set<string>());
  const key = restartKey(config);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    // Guards the async import: if this effect is cleaned up first (unmount,
    // a restart-key change, or React Strict Mode's mount-unmount-mount), the
    // stale import must not initialize the SDK or set state.
    let cancelled = false;
    let started: AetherSDKInterface | null = null;

    loadSdk()
      .then(({ default: aether }) => {
        if (cancelled) return;
        aether.init(configRef.current);
        started = aether;
        _instance = aether;
        initializedWith.current = configRef.current;
        setSdk(aether);
      })
      .catch((error: unknown) => {
        if (!cancelled) console.error('[Aether] failed to load or initialize the SDK', error);
      });

    return () => {
      cancelled = true;
      if (started) {
        started.destroy?.();
        if (_instance === started) _instance = null;
      }
      initializedWith.current = null;
      setSdk(null);
    };
  }, [key]);

  // Options other than the restart keys are not re-applied after init. Warn
  // (once per option, development only) when a primitive one changes, so a
  // silently ignored change is visible.
  useEffect(() => {
    const base = initializedWith.current;
    if (!base || !isDevelopment()) return;
    for (const [name, value] of Object.entries(config)) {
      if ((RESTART_KEYS as readonly string[]).includes(name) || warned.current.has(name)) continue;
      const before = (base as unknown as Record<string, unknown>)[name];
      const primitive = value === null || ['string', 'number', 'boolean', 'undefined'].includes(typeof value);
      if (primitive && before !== value) {
        warned.current.add(name);
        console.warn(
          `[Aether] AetherProvider config.${name} changed after init and is ignored. ` +
            `Only ${RESTART_KEYS.join(', ')} restart the SDK.`,
        );
      }
    }
  });

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
