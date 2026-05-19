// =============================================================================
// Aether SDK — React Native Bridge
// Unified JS API bridging to native iOS/Android modules
// =============================================================================

import { NativeModules, NativeEventEmitter, Platform } from 'react-native';
import { useState, useEffect, useCallback, createContext, useContext, ReactNode } from 'react';

const { AetherNative } = NativeModules;
const emitter = AetherNative ? new NativeEventEmitter(AetherNative) : null;

// =============================================================================
// TYPES
// =============================================================================

export interface AetherRNConfig {
  apiKey: string;
  environment?: 'production' | 'staging' | 'development';
  debug?: boolean;
  endpoint?: string;
  modules?: {
    screenTracking?: boolean;
    deepLinkAttribution?: boolean;
    pushTracking?: boolean;
    walletTracking?: boolean;
    experiments?: boolean;
  };
  privacy?: {
    gdprMode?: boolean;
    anonymizeIP?: boolean;
  };
}

export interface Identity {
  anonymousId: string;
  userId?: string;
  traits: Record<string, unknown>;
}

export interface IdentityData {
  userId?: string;
  walletAddress?: string;
  walletType?: string;
  chainId?: number;
  traits?: Record<string, unknown>;
}

// =============================================================================
// CORE API
// =============================================================================

const Aether = {
  init(config: AetherRNConfig): void {
    if (!AetherNative) {
      console.warn('[Aether RN] Native module not linked. Run `npx pod-install` (iOS) or rebuild (Android).');
      return;
    }
    AetherNative.initialize(config);
  },

  track(event: string, properties?: Record<string, unknown>): void {
    AetherNative?.track(event, properties ?? {});
  },

  screenView(screenName: string, properties?: Record<string, unknown>): void {
    AetherNative?.screenView(screenName, properties ?? {});
  },

  conversion(event: string, value?: number, properties?: Record<string, unknown>): void {
    AetherNative?.conversion(event, value ?? 0, properties ?? {});
  },

  hydrateIdentity(data: IdentityData): void {
    AetherNative?.hydrateIdentity(data);
  },

  async getIdentity(): Promise<Identity> {
    return AetherNative?.getIdentity() ?? { anonymousId: '', traits: {} };
  },

  reset(): void {
    AetherNative?.reset();
  },

  flush(): void {
    AetherNative?.flush();
  },

  handleDeepLink(url: string): void {
    AetherNative?.handleDeepLink(url);
  },

  trackPushOpened(data: Record<string, string>): void {
    AetherNative?.trackPushOpened(data);
  },

  // Wallet
  wallet: {
    connect(address: string, options?: { type?: string; chainId?: number }): void {
      AetherNative?.walletConnect(address, options ?? {});
    },
    disconnect(): void {
      AetherNative?.walletDisconnect();
    },
    transaction(txHash: string, options?: Record<string, unknown>): void {
      AetherNative?.walletTransaction(txHash, options ?? {});
    },
  },

  // Experiments
  experiments: {
    async run(id: string, variants: string[]): Promise<string> {
      return AetherNative?.runExperiment(id, variants) ?? variants[0];
    },
    async getAssignment(id: string): Promise<string | null> {
      return AetherNative?.getExperimentAssignment(id) ?? null;
    },
  },

  // Consent
  consent: {
    async getState(): Promise<{ analytics: boolean; marketing: boolean; web3: boolean }> {
      return AetherNative?.getConsentState() ?? { analytics: false, marketing: false, web3: false };
    },
    grant(purposes: string[]): void {
      AetherNative?.grantConsent(purposes);
    },
    revoke(purposes: string[]): void {
      AetherNative?.revokeConsent(purposes);
    },
  },
};

// =============================================================================
// REACT HOOKS
// =============================================================================

export function useAether() {
  return Aether;
}

export function useIdentity() {
  const [identity, setIdentity] = useState<Identity | null>(null);

  useEffect(() => {
    Aether.getIdentity().then(setIdentity);
    const sub = emitter?.addListener('AetherIdentityChanged', setIdentity);
    return () => sub?.remove();
  }, []);

  const hydrate = useCallback((data: IdentityData) => {
    Aether.hydrateIdentity(data);
    Aether.getIdentity().then(setIdentity);
  }, []);

  return { identity, hydrate, reset: Aether.reset };
}

export function useExperiment(id: string, variants: string[]) {
  const [variant, setVariant] = useState<string | null>(null);

  useEffect(() => {
    Aether.experiments.run(id, variants).then(setVariant);
  }, [id]);

  return variant;
}

export function useScreenTracking(screenName: string) {
  useEffect(() => {
    Aether.screenView(screenName);
  }, [screenName]);
}

// =============================================================================
// CONTEXT PROVIDER
// =============================================================================

interface AetherContextValue {
  aether: typeof Aether;
  isInitialized: boolean;
}

const AetherContext = createContext<AetherContextValue>({
  aether: Aether,
  isInitialized: false,
});

export function AetherProvider({
  config,
  children,
}: {
  config: AetherRNConfig;
  children: ReactNode;
}) {
  const [isInitialized, setIsInitialized] = useState(false);

  useEffect(() => {
    Aether.init(config);
    setIsInitialized(true);
  }, [config.apiKey]);

  return (
    <AetherContext.Provider value={{ aether: Aether, isInitialized }}>
      {children}
    </AetherContext.Provider>
  );
}

export function useAetherContext() {
  return useContext(AetherContext);
}

export default Aether;
