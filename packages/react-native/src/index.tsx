// =============================================================================
// Aether SDK — React Native Bridge
// Unified JS API bridging to native iOS/Android modules
// =============================================================================

// All non-JSX exports (types, Aether object, hooks, context value) live in
// bridge.ts so tests can import them without triggering JSX parsing.
export {
  useAether,
  useIdentity,
  useExperiment,
  useScreenTracking,
  useConsentState,
  useJourneyResumed,
  useAetherContext,
  AetherContext,
  default,
} from './bridge';
export type {
  ResolvedIdentity,
  AetherRNConfig,
  Identity,
  IdentityData,
  AetherContextValue,
} from './bridge';

import React, { useState, useEffect, ReactNode } from 'react';
import Aether, { AetherContext, emitter, AetherRNConfig } from './bridge';
import { semanticContext } from './context/SemanticContext';
import { RNEcommerce } from './modules/Ecommerce';
import { RNFeatureFlags } from './modules/FeatureFlags';
import { RNFeedback } from './modules/Feedback';
import { RNHealthAgent } from './modules/HealthAgent';
import type { ResolvedIdentity } from './bridge';

// =============================================================================
// CONTEXT PROVIDER — the only JSX in the React Native package
// =============================================================================

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
      .then(_cfg => { /* store config */ })
      .catch(() => { /* silent */ });

    // Cache fingerprint ID
    Aether.getFingerprint().catch(() => {});

    // Wire onJourneyResumed callback if provided
    let journeySub: ReturnType<NonNullable<typeof emitter>['addListener']> | undefined;
    if (config.onJourneyResumed && emitter) {
      journeySub = emitter.addListener('AetherJourneyResumed', config.onJourneyResumed as (identity: ResolvedIdentity) => void);
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
