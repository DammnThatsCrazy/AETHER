// =============================================================================
// Aether SDK — React Native Bridge
// Unified JS API bridging to native iOS/Android modules
// =============================================================================

import { NativeModules, NativeEventEmitter, Platform } from 'react-native';
import { useState, useEffect, useCallback, createContext, useContext, ReactNode } from 'react';
import React from 'react';
import { semanticContext } from './context/SemanticContext';
import { RNEcommerce } from './modules/Ecommerce';
import { RNFeatureFlags } from './modules/FeatureFlags';
import { RNFeedback } from './modules/Feedback';
import { RNHealthAgent } from './modules/HealthAgent';
import type { ConsentState, ConsentPurpose } from '@aether/shared/consent';

const { AetherNative } = NativeModules;
const emitter = AetherNative ? new NativeEventEmitter(AetherNative) : null;

// =============================================================================
// TYPES
// =============================================================================

export interface ResolvedIdentity {
  userId?: string;
  anonymousId?: string;
  traits?: Record<string, unknown>;
}

export interface AetherRNConfig {
  apiKey: string;
  environment?: 'production' | 'staging' | 'development';
  /** Host app version, reported in SDK fleet heartbeats. */
  appVersion?: string;
  debug?: boolean;
  endpoint?: string;
  modules?: {
    screenTracking?: boolean;
    deepLinkAttribution?: boolean;
    pushTracking?: boolean;
    walletTracking?: boolean;
    experiments?: boolean;
    performance?: boolean;
  };
  privacy?: {
    gdprMode?: boolean;
    anonymizeIP?: boolean;
  };
  autoResumeJourney?: boolean;
  onJourneyResumed?: (identity: ResolvedIdentity) => void;
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
    semanticContext.recordScreen(screenName);
    AetherNative?.screenView(screenName, properties ?? {});
  },

  conversion(event: string, value?: number, properties?: Record<string, unknown>): void {
    AetherNative?.conversion(event, value ?? 0, properties ?? {});
  },

  hydrateIdentity(data: IdentityData): void {
    AetherNative?.hydrateIdentity(data);
  },

  startJourney(nameOrType: string, properties?: Record<string, unknown>): void {
    AetherNative?.startJourney(nameOrType, properties ?? {});
  },

  pauseJourney(reason?: string, properties?: Record<string, unknown>): void {
    AetherNative?.pauseJourney(reason ?? '', properties ?? {});
  },

  resumeJourney(reason?: string, properties?: Record<string, unknown>): void {
    AetherNative?.resumeJourney(reason ?? '', properties ?? {});
  },

  continueJourney(stepIdOrName: string, properties?: Record<string, unknown>): void {
    AetherNative?.continueJourney(stepIdOrName, properties ?? {});
  },

  completeJourney(reason?: string, properties?: Record<string, unknown>): void {
    AetherNative?.completeJourney(reason ?? '', properties ?? {});
  },

  abandonJourney(reason?: string, properties?: Record<string, unknown>): void {
    AetherNative?.abandonJourney(reason ?? '', properties ?? {});
  },

  checkpointJourney(stepIdOrName: string, properties?: Record<string, unknown>): void {
    AetherNative?.checkpointJourney(stepIdOrName, properties ?? {});
  },

  async getCurrentJourney(): Promise<Record<string, unknown> | null> {
    return AetherNative?.getCurrentJourney?.() ?? null;
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

  async getFingerprint(): Promise<string> {
    try {
      return await NativeModules.AetherNative.getFingerprint();
    } catch {
      return '';
    }
  },

  handleDeepLink(url: string): void {
    AetherNative?.handleDeepLink(url);
  },

  trackPushOpened(data: Record<string, string>): void {
    AetherNative?.trackPushOpened(data);
  },

  // Wallet
  wallet: {
    connect(address: string, options?: { type?: string; chainId?: number; vm?: string }): void {
      AetherNative?.walletConnect(address, options ?? {});
    },
    disconnect(address: string): void {
      AetherNative?.walletDisconnect(address);
    },
    transaction(txHash: string, options?: Record<string, unknown>): void {
      AetherNative?.walletTransaction(txHash, options ?? {});
    },
    contractAction(contract: string, action: string, options?: Record<string, unknown>): void {
      AetherNative?.contractAction?.(contract, action, options ?? {});
    },
    walletConnectSession(topic: string, options?: { address?: string; chainId?: string; [k: string]: unknown }): void {
      AetherNative?.trackWalletConnectSession?.(topic, options ?? {});
    },
    async getCapabilities(): Promise<Record<string, unknown>> {
      return AetherNative?.getWalletCapabilities?.() ?? { connected: false, addresses: [], supportedVMs: [] };
    },
  },

  commerce: {
    paymentInitiated(paymentId: string, amount: number, currency: string, properties?: Record<string, unknown>): void { AetherNative?.paymentInitiated?.(paymentId, amount, currency, properties ?? {}); },
    paymentCompleted(paymentId: string, amount: number, currency: string, properties?: Record<string, unknown>): void { AetherNative?.paymentCompleted?.(paymentId, amount, currency, properties ?? {}); },
    paymentFailed(paymentId: string, reason: string, properties?: Record<string, unknown>): void { AetherNative?.paymentFailed?.(paymentId, reason, properties ?? {}); },
    applePayPayment(status: 'initiated' | 'completed' | 'failed', options?: { amount?: number; currency?: string; [k: string]: unknown }): void {
      if (Platform.OS === 'ios') AetherNative?.trackApplePayPayment?.(status, options ?? {});
    },
    googlePayPayment(status: 'initiated' | 'completed' | 'failed', options?: { amount?: number; currency?: string; [k: string]: unknown }): void {
      if (Platform.OS === 'android') AetherNative?.trackGooglePayPayment?.(status, options ?? {});
    },
    approvalRequested(approvalId: string, scope: string, properties?: Record<string, unknown>): void { AetherNative?.approvalRequested?.(approvalId, scope, properties ?? {}); },
    approvalResolved(approvalId: string, approved: boolean, properties?: Record<string, unknown>): void { AetherNative?.approvalResolved?.(approvalId, approved, properties ?? {}); },
    entitlementGranted(entitlementId: string, properties?: Record<string, unknown>): void { AetherNative?.entitlementGranted?.(entitlementId, properties ?? {}); },
    entitlementRevoked(entitlementId: string, properties?: Record<string, unknown>): void { AetherNative?.entitlementRevoked?.(entitlementId, properties ?? {}); },
    accessGranted(resource: string, properties?: Record<string, unknown>): void { AetherNative?.accessGranted?.(resource, properties ?? {}); },
    accessDenied(resource: string, reason: string, properties?: Record<string, unknown>): void { AetherNative?.accessDenied?.(resource, reason, properties ?? {}); },
  },

  agent: {
    task(taskId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTask?.(taskId, actorId, properties ?? {}); },
    decision(decisionId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.agentDecision?.(decisionId, actorId, properties ?? {}); },
    a2hInteraction(interactionId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.a2hInteraction?.(interactionId, actorId, properties ?? {}); },
  },

  x402: {
    payment(paymentId: string, amount: string, currency: string, network: string, properties?: Record<string, unknown>): void {
      AetherNative?.x402Payment?.(paymentId, amount, currency, network, properties ?? {});
    },
  },

  capabilities: {
    automaticWalletDetection: false,
    manualMultiVmWalletEmitters: true,
    nativeOfflinePersistence: true,
    remoteManifest: true,
    healthHeartbeat: true,
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

  // Consent — 5 canonical purposes (see packages/shared/consent.ts)
  consent: {
    async getState(): Promise<ConsentState> {
      return AetherNative?.getConsentState() ?? {
        analytics: false, marketing: false, web3: false, agent: false, commerce: false,
        updatedAt: '', policyVersion: '',
      };
    },
    grant(purposes: ConsentPurpose[]): void {
      AetherNative?.grantConsent(purposes);
    },
    revoke(purposes: ConsentPurpose[]): void {
      AetherNative?.revokeConsent(purposes);
    },
    onUpdate(callback: (state: ConsentState) => void): () => void {
      const sub = emitter?.addListener('AetherConsentChanged', callback);
      return () => sub?.remove();
    },
  },

  // E-commerce
  ecommerce: RNEcommerce,

  // Feature Flags
  featureFlag: RNFeatureFlags,

  // Feedback Surveys
  feedback: RNFeedback,
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

export function useConsentState() {
  const [consent, setConsent] = useState<ConsentState | null>(null);

  useEffect(() => {
    Aether.consent.getState().then(setConsent);
    return Aether.consent.onUpdate(setConsent);
  }, []);

  return {
    consent,
    grant: Aether.consent.grant,
    revoke: Aether.consent.revoke,
  };
}

export function useJourneyResumed(): ResolvedIdentity | null {
  const [resumedIdentity, setResumedIdentity] = useState<ResolvedIdentity | null>(null);

  useEffect(() => {
    const sub = emitter?.addListener('AetherJourneyResumed', (identity: ResolvedIdentity) => {
      setResumedIdentity(identity);
    });
    return () => sub?.remove();
  }, []);

  return resumedIdentity;
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
    const endpoint = config.endpoint ?? 'https://api.aether.io';

    Aether.init(config);
    semanticContext.resetSession();

    // Initialize Web2 modules
    RNEcommerce.initialize(config.apiKey, endpoint);
    RNFeatureFlags.initialize(config.apiKey, endpoint);
    RNFeedback.initialize(config.apiKey, endpoint);

    // SDK fleet self-identification. For GDPR opt-in deployments, defer
    // heartbeats until the user grants analytics consent (consent is owned by
    // the native layer and surfaced via Aether.consent).
    let healthAgent: RNHealthAgent | null = null;
    let consentUnsub: (() => void) | undefined;
    const startHealthAgent = () => {
      if (healthAgent) return;
      healthAgent = new RNHealthAgent({
        endpoint,
        apiKey: config.apiKey,
        appVersion: config.appVersion,
      });
      healthAgent.start();
    };

    if (config.privacy?.gdprMode) {
      Aether.consent.getState()
        .then((state) => { if (state?.analytics) startHealthAgent(); })
        .catch(() => { /* consent unavailable — stay deferred */ });
      consentUnsub = Aether.consent.onUpdate((state) => {
        if (state?.analytics) {
          startHealthAgent();
          consentUnsub?.();
          consentUnsub = undefined;
        }
      });
    } else {
      startHealthAgent();
    }

    setIsInitialized(true);

    // Journey foreground/background lifecycle is emitted by the native SDKs
    // (Android onStart/onStop, iOS willEnterForeground). Emitting the same
    // transitions again from a JS AppState listener would double-count every
    // active/background change in the stitcher, so lifecycle emission is left
    // to native.

    // Fetch server config (non-blocking, fire-and-forget)
    fetch(`${endpoint}/v1/config?apiKey=${config.apiKey}`)
      .then(r => r.json())
      .then(cfg => { /* store config */ })
      .catch(() => { /* silent */ });

    // Cache fingerprint ID
    Aether.getFingerprint().catch(() => {});

    // Wire onJourneyResumed callback if provided
    let journeySub: ReturnType<NonNullable<typeof emitter>['addListener']> | undefined;
    if (config.onJourneyResumed && emitter) {
      journeySub = emitter.addListener('AetherJourneyResumed', config.onJourneyResumed);
    }

    return () => {
      journeySub?.remove();
      consentUnsub?.();
      healthAgent?.stop();
      semanticContext.destroy();
      RNEcommerce.destroy();
      RNFeatureFlags.destroy();
      RNFeedback.destroy();
    };
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
