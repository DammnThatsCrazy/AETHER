// =============================================================================
// Aether SDK — React Native Bridge (non-JSX core)
// All public API, types, and hooks live here so they can be imported and
// tested without triggering JSX parsing.  AetherProvider (JSX) stays in
// index.tsx and re-exports from this file.
// =============================================================================

import { NativeModules, NativeEventEmitter, Platform } from 'react-native';
import { useState, useEffect, useCallback, createContext, useContext } from 'react';
import { semanticContext } from './context/SemanticContext';
import type { SemanticContextEnvelope } from './context/SemanticContext';
import { RNEcommerce } from './modules/Ecommerce';
import { RNFeatureFlags } from './modules/FeatureFlags';
import { RNFeedback } from './modules/Feedback';
import type { ConsentState, ConsentPurpose } from '@aether/shared/consent';
import {
  buildCanonicalConsentReceipt,
  type CanonicalConsentReceiptInput,
} from '@aether/shared/consent-receipt';

export const { AetherNative } = NativeModules;
export const emitter = AetherNative ? new NativeEventEmitter(AetherNative) : null;
let activeConfig: AetherRNConfig | null = null;

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

/**
 * Per-batch ingestion health counters (Truth Kernel §2.8), delivered from the
 * native layer via the `AetherBatchResult` event. `accepted` / `duplicate` /
 * `rejected` come from the backend BatchResponse; `dropped_by_consent` and
 * `queue_depth` are native SDK-side truths.
 */
export interface BatchHealth {
  accepted: number;
  duplicate: number;
  rejected: number;
  dropped_by_consent: number;
  queue_depth: number;
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
    activeConfig = config;
    AetherNative.initialize(config);
  },

  track(event: string, properties?: Record<string, unknown>): void {
    AetherNative?.track(event, properties ?? {});
  },

  /**
   * Canonical low-level observation API (Truth Kernel §2.6). Emits a first-class
   * backend event `type` directly through the native pipeline, which applies the
   * same consent gating, batching, and queue-depth limits as `track`. Unknown
   * (non-canonical) types are a native-side no-op, never a mislabeled event.
   */
  observe(type: string, properties?: Record<string, unknown>): void {
    AetherNative?.observe?.(type, properties ?? {});
  },

  /** Current native event-queue depth (Truth Kernel §2.6 queue-depth awareness). */
  async queueDepth(): Promise<number> {
    try {
      return (await AetherNative?.getQueueDepth?.()) ?? 0;
    } catch {
      return 0;
    }
  },

  /**
   * Subscribe to per-batch ingestion health (Truth Kernel §2.8) emitted by the
   * native layer after each delivered batch. Returns an unsubscribe function.
   */
  onBatchResult(callback: (health: BatchHealth) => void): () => void {
    const sub = emitter?.addListener('AetherBatchResult', callback);
    return () => sub?.remove();
  },

  screenView(screenName: string, properties?: Record<string, unknown>): void {
    semanticContext.recordScreen(screenName);
    AetherNative?.screenView(screenName, properties ?? {});
  },

  /**
   * Build the JS-side Tier 1 semantic envelope (device, viewport, temporal
   * provenance, JS screen trail) around ids the caller already holds.
   *
   * RN events ship through the NATIVE pipeline: native `track()`/`observe()`
   * accept only `(type, properties)`, stamp the canonical sessionId/eventId
   * natively, and build their own event context — and the native module
   * exposes no session getter to JS. The envelope therefore cannot be
   * attached in-band without inventing a native method or smuggling context
   * into user properties (no such reserved key exists in the native SDKs).
   * Instead it is exposed here for consumers that hold the canonical ids —
   * the host app or the native layer — e.g. side-channel transports that
   * want the JS screen trail alongside a natively-identified event.
   *
   * The collector never mints ids (parity with the web SDK's
   * SemanticContextCollector.collect(sessionId, eventId)), so the returned
   * envelope always agrees with the ids passed in.
   */
  collectSemanticContext(sessionId: string, eventId: string): SemanticContextEnvelope {
    return semanticContext.collect(sessionId, eventId);
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
    // Native reset() re-mints the native session id. Clear the JS screen
    // trail at the same boundary so the next semantic envelope never carries
    // a trail from the previous session.
    semanticContext.resetSession();
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
      return (await AetherNative?.getWalletCapabilities?.()) ?? { connected: false, addresses: [], supportedVMs: [] };
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
    removeFromCart(productId: string, quantity: number, properties?: Record<string, unknown>): void { AetherNative?.trackRemoveFromCart?.(productId, quantity, properties ?? {}); },
    applyCoupon(couponCode: string, properties?: Record<string, unknown>): void { AetherNative?.trackApplyCoupon?.(couponCode, properties ?? {}); },
    beginCheckout(cartValue: number, currency: string, properties?: Record<string, unknown>): void { AetherNative?.trackBeginCheckout?.(cartValue, currency, properties ?? {}); },
  },

  agent: {
    task(taskId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTask?.(taskId, actorId, properties ?? {}); },
    decision(decisionId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.agentDecision?.(decisionId, actorId, properties ?? {}); },
    a2hInteraction(interactionId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.a2hInteraction?.(interactionId, actorId, properties ?? {}); },
    registered(agentId: string, properties?: Record<string, unknown>): void { AetherNative?.agentRegistered?.(agentId, properties ?? {}); },
    updated(agentId: string, properties?: Record<string, unknown>): void { AetherNative?.agentUpdated?.(agentId, properties ?? {}); },
    authorized(agentId: string, delegationId?: string, properties?: Record<string, unknown>): void { AetherNative?.agentAuthorized?.(agentId, delegationId ?? '', properties ?? {}); },
    deauthorized(agentId: string, properties?: Record<string, unknown>): void { AetherNative?.agentDeauthorized?.(agentId, properties ?? {}); },
    capabilityGranted(agentId: string, capability: string, properties?: Record<string, unknown>): void { AetherNative?.agentCapabilityGranted?.(agentId, capability, properties ?? {}); },
    capabilityRevoked(agentId: string, capability: string, properties?: Record<string, unknown>): void { AetherNative?.agentCapabilityRevoked?.(agentId, capability, properties ?? {}); },
    taskCreated(taskId: string, actorId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTaskCreated?.(taskId, actorId, properties ?? {}); },
    taskDecomposed(taskId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTaskDecomposed?.(taskId, properties ?? {}); },
    taskStarted(taskId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTaskStarted?.(taskId, properties ?? {}); },
    taskCompleted(taskId: string, properties?: Record<string, unknown>): void { AetherNative?.agentTaskCompleted?.(taskId, properties ?? {}); },
    taskFailed(taskId: string, reason?: string, properties?: Record<string, unknown>): void { AetherNative?.agentTaskFailed?.(taskId, reason ?? '', properties ?? {}); },
    toolCalled(taskId: string, tool: string, properties?: Record<string, unknown>): void { AetherNative?.agentToolCalled?.(taskId, tool, properties ?? {}); },
    resourceRequested(resourceId: string, properties?: Record<string, unknown>): void { AetherNative?.agentResourceRequested?.(resourceId, properties ?? {}); },
    delegatedTask(taskId: string, toAgentId: string, properties?: Record<string, unknown>): void { AetherNative?.agentDelegatedTask?.(taskId, toAgentId, properties ?? {}); },
    subagentSpawned(parentId: string, childId: string, properties?: Record<string, unknown>): void { AetherNative?.agentSubagentSpawned?.(parentId, childId, properties ?? {}); },
    policyEvaluated(policyId: string, outcome: string, properties?: Record<string, unknown>): void { AetherNative?.agentPolicyEvaluated?.(policyId, outcome, properties ?? {}); },
    handoff(fromId: string, toId: string, properties?: Record<string, unknown>): void { AetherNative?.agentHandoff?.(fromId, toId, properties ?? {}); },
    escalatedToHuman(taskId: string, reason?: string, properties?: Record<string, unknown>): void { AetherNative?.agentEscalatedToHuman?.(taskId, reason ?? '', properties ?? {}); },
    outcomeRecorded(taskId: string, outcome: string, properties?: Record<string, unknown>): void { AetherNative?.agentOutcomeRecorded?.(taskId, outcome, properties ?? {}); },
  },

  x402: {
    payment(paymentId: string, amount: string, currency: string, network: string, properties?: Record<string, unknown>): void {
      AetherNative?.x402Payment?.(paymentId, amount, currency, network, properties ?? {});
    },
    resourceRequested(resourceId: string, properties?: Record<string, unknown>): void { AetherNative?.x402ResourceRequested?.(resourceId, properties ?? {}); },
    paymentRequired(resourceId: string, amount: number, currency: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentRequired?.(resourceId, amount, currency, properties ?? {}); },
    quoteReceived(quoteId: string, properties?: Record<string, unknown>): void { AetherNative?.x402QuoteReceived?.(quoteId, properties ?? {}); },
    authorizationRequested(paymentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402AuthorizationRequested?.(paymentId, properties ?? {}); },
    authorizationResolved(paymentId: string, authorized: boolean, properties?: Record<string, unknown>): void { AetherNative?.x402AuthorizationResolved?.(paymentId, authorized, properties ?? {}); },
    paymentIntentCreated(intentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentIntentCreated?.(intentId, properties ?? {}); },
    paymentSubmitted(paymentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentSubmitted?.(paymentId, properties ?? {}); },
    paymentSettled(paymentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentSettled?.(paymentId, properties ?? {}); },
    paymentFailed(paymentId: string, reason?: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentFailed?.(paymentId, reason ?? '', properties ?? {}); },
    paymentTimeout(paymentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402PaymentTimeout?.(paymentId, properties ?? {}); },
    receiptVerified(receiptId: string, properties?: Record<string, unknown>): void { AetherNative?.x402ReceiptVerified?.(receiptId, properties ?? {}); },
    accessGranted(resourceId: string, properties?: Record<string, unknown>): void { AetherNative?.x402AccessGranted?.(resourceId, properties ?? {}); },
    accessDenied(resourceId: string, reason?: string, properties?: Record<string, unknown>): void { AetherNative?.x402AccessDenied?.(resourceId, reason ?? '', properties ?? {}); },
    refundOrReversal(paymentId: string, properties?: Record<string, unknown>): void { AetherNative?.x402RefundOrReversal?.(paymentId, properties ?? {}); },
  },

  rewards: {
    actionQueued(campaignId: string, ruleId: string, properties?: Record<string, unknown>): void { AetherNative?.rewardActionQueued?.(campaignId, ruleId, properties ?? {}); },
    proofGenerated(campaignId: string, proofId: string, properties?: Record<string, unknown>): void { AetherNative?.rewardProofGenerated?.(campaignId, proofId, properties ?? {}); },
    delivered(campaignId: string, rewardId: string, properties?: Record<string, unknown>): void { AetherNative?.rewardDelivered?.(campaignId, rewardId, properties ?? {}); },
    claimSubmitted(campaignId: string, claimId: string, properties?: Record<string, unknown>): void { AetherNative?.rewardClaimSubmitted?.(campaignId, claimId, properties ?? {}); },
  },

  capabilities: {
    automaticWalletDetection: false,
    manualMultiVmWalletEmitters: true,
    nativeOfflinePersistence: true,
    remoteManifest: true,
    healthHeartbeat: true,
    // Canonical observe() bridged to native (Truth Kernel §2.6).
    observe: true,
    // Per-batch ingestion health via the AetherBatchResult native event (§2.8).
    batchHealth: true,
    // Manifest signature verification is enforced in the native iOS/Android
    // layers this bridge delegates to (§2.9).
    manifestSignatureVerification: true,
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
        analytics: false,
        marketing: false,
        personalization: false,
        web3: false,
        agent: false,
        commerce: false,
        credit: false,
        location: false,
        updatedAt: '',
        policyVersion: '',
      };
    },
    grant(purposes: ConsentPurpose[]): void {
      AetherNative?.grantConsent(purposes);
    },
    /**
     * Grant all non-explicit-opt-in purposes (excludes credit and location).
     * Passes through to native grantAll() which enforces the same exclusion.
     */
    grantAll(): void {
      const grantable: ConsentPurpose[] = [
        'analytics', 'marketing', 'personalization', 'web3', 'agent', 'commerce',
      ];
      AetherNative?.grantConsent(grantable);
    },
    revoke(purposes: ConsentPurpose[]): void {
      AetherNative?.revokeConsent(purposes);
    },
    onUpdate(callback: (state: ConsentState) => void): () => void {
      const sub = emitter?.addListener('AetherConsentChanged', callback);
      return () => sub?.remove();
    },
    async recordReceipt(input: CanonicalConsentReceiptInput) {
      if (!activeConfig) throw new Error('Aether SDK is not initialized');
      const receipt = await buildCanonicalConsentReceipt(input);
      const endpoint = activeConfig.endpoint ?? 'https://api.aether.io';
      const response = await fetch(`${endpoint}/v1/consent/records`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${activeConfig.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          user_id: receipt.subject_id,
          subject_id: receipt.subject_id,
          anonymous_id: receipt.anonymous_id,
          purposes: receipt.purposes,
          granted: receipt.state === 'granted',
          source: receipt.source,
          mode: receipt.mode,
          jurisdiction: receipt.jurisdiction_context,
          gpc_observed: receipt.gpc_observed,
          dnt_observed: receipt.dnt_observed,
          idempotency_key: receipt.idempotency_key,
          canonical_receipt: receipt,
        }),
      });
      if (!response.ok) {
        throw new Error(`Consent receipt request failed (${response.status})`);
      }
      return receipt;
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

/* v8 ignore start — React hooks require a rendering context; tested via integration */
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
/* v8 ignore stop */

// =============================================================================
// CONTEXT (value type + hook — provider JSX lives in index.tsx)
// =============================================================================

export interface AetherContextValue {
  aether: typeof Aether;
  isInitialized: boolean;
}

export const AetherContext = createContext<AetherContextValue>({
  aether: Aether,
  isInitialized: false,
});

/* v8 ignore next 3 */
export function useAetherContext() {
  return useContext(AetherContext);
}

export default Aether;
