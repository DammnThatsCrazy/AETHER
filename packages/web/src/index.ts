// =============================================================================
// Aether SDK — MAIN CLASS (Tier 2 Thin Client)
// Public API orchestrating: identity, session, events, web3, commerce,
// agent, x402.
//
// Canonical contracts live in packages/shared/*.ts. This SDK mirrors them.
// The SDK is OBSERVATION-ONLY: no workflow, approvals, or settlement logic
// runs client-side. The backend owns enrichment, classification, graph
// mutation, and all orchestration.
// =============================================================================

import type {
  AetherConfig, AetherSDKInterface, AetherPlugin,
  IdentityData, Identity, WalletInfo, TransactionOptions,
  VMType, ConsentCallback, ConnectedWallet, ResolvedIdentity,
  ConsentState, ConsentPurpose, ConsentBannerConfig, WalletInterface, ConsentInterface,
  CommerceInterface, AgentInterface, X402Interface,
  CurrentJourney, JourneyLifecycleEventType, JourneyPayload,
} from './types';
import { EventQueue } from './core/event-queue';
import { SessionManager } from './core/session';
import { IdentityManager } from './core/identity';
import { AutoDiscoveryModule } from './modules/auto-discovery';
import { ConsentModule } from './consent';
import { Web3Module } from './web3';
import { SemanticContextCollector } from './context/semantic-context';
import { TrafficSourceTracker } from './tracking/traffic-source-tracker';
import { RewardClient, createRewardClient } from './rewards/reward-client';
import { EcommerceModule } from './modules/ecommerce';
import { FormAnalyticsModule } from './modules/form-analytics';
import { FeatureFlagModule } from './modules/feature-flags';
import { HeatmapModule } from './modules/heatmaps';
import { FunnelModule } from './modules/funnels';
import type { FunnelDefinition } from './modules/funnels';
import { PerformanceModule } from './modules/performance';
import { DeviceFingerprintCollector } from './core/fingerprint';
import { SDKHealthAgent } from './health/sdk-health-agent';
import type { SDKManifest as RemoteSDKManifest } from './health/sdk-health-agent';
import { generateId, now, getPageContext, getDeviceContext, getCampaignContext } from './utils';
import { createModuleProxy } from './utils/module-proxy';

const SDK_VERSION = '8.11.0'; // synchronized by scripts/bump-sdk-version.sh and scripts/validate_sdk_release_alignment.py
const DEFAULT_ENDPOINT = 'https://api.aether.io';

class AetherSDK implements AetherSDKInterface {
  private config: AetherConfig | null = null;
  private eventQueue: EventQueue | null = null;
  private sessionManager: SessionManager | null = null;
  private identityManager: IdentityManager | null = null;
  private autoDiscovery: AutoDiscoveryModule | null = null;
  private consentModule: ConsentModule | null = null;
  private web3Module: Web3Module | null = null;
  private semanticContext: SemanticContextCollector | null = null;
  private trafficTracker: TrafficSourceTracker | null = null;
  private rewardClient: RewardClient | null = null;
  private ecommerceModule: EcommerceModule | null = null;
  private formAnalytics: FormAnalyticsModule | null = null;
  private featureFlags: FeatureFlagModule | null = null;
  private heatmapModule: HeatmapModule | null = null;
  private funnelModule: FunnelModule | null = null;
  private performanceModule: PerformanceModule | null = null;
  private fingerprintCollector: DeviceFingerprintCollector | null = null;
  private plugins: AetherPlugin[] = [];
  private initialized = false;
  private debug = false;
  private _lastEmailHash: string | undefined = undefined;
  private healthAgent: SDKHealthAgent | null = null;
  private healthAgentConsentUnsub: (() => void) | null = null;
  private sdkInstanceId: string | null = null;
  /** Remote-config feature switches from the active manifest (empty = all on). */
  private remoteFeatures: Record<string, boolean> = {};
  private currentJourney: CurrentJourney | null = null;
  private journeyResumeListeners: Array<(identity: ResolvedIdentity) => void> = [];
  private lastJourneyPauseAt: number | null = null;
  private journeyVisibilityHandler: (() => void) | null = null;
  private lastRouteCheckpointPath: string | null = null;

  // Wallet change listeners
  private walletChangeListeners: ((wallets: ConnectedWallet[]) => void)[] = [];

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  init(config: AetherConfig): void {
    if (this.initialized) {
      this.log('warn', 'Aether SDK already initialized. Call destroy() first to reinitialize.');
      return;
    }

    if (!config.apiKey) {
      throw new Error('Aether SDK: apiKey is required');
    }

    this.config = config;
    this.debug = config.debug ?? false;
    this.log('info', 'Initializing Aether SDK v' + SDK_VERSION);

    const modules = config.modules ?? {};

    this.initCore(config);
    this.initWeb3(config, modules);
    this.initWeb2(config, modules);
    this.initAnalytics(config, modules);

    // Fetch backend config (feature flags, funnel definitions, etc.)
    this.fetchConfig().catch(() => {
      this.log('warn', 'Failed to fetch remote config — using defaults');
    });

    this.pageView();
    this.setupSPATracking();
    this.setupJourneyLifecycleTracking();

    if (config.privacy?.respectDNT && navigator.doNotTrack === '1') {
      this.log('info', 'DNT detected — limiting data collection');
    }

    // Self-identify to the backend SDK fleet and apply remote config. Gated on
    // analytics consent + DNT so it never collects ahead of the SDK's own
    // pre-consent guard.
    this.startHealthAgent();

    this.initialized = true;
    this.log('info', 'Aether SDK v8.11.0 initialized — Tier 2 thin client');
  }

  track(event: string, properties?: Record<string, unknown>): void {
    this.enqueueEvent('track', { event, ...properties });
    this.sessionManager?.recordEvent();
  }

  /**
   * Emit a canonical 'error' event (gated on analytics consent).
   * Automatically extracts message, name, and stack from an Error instance.
   *
   * @param message  Human-readable error description
   * @param error    Optional Error instance (stack/name auto-captured)
   * @param properties  Additional key/value context to attach
   */
  error(message: string, error?: Error | unknown, properties?: Record<string, unknown>): void {
    const errorProps: Record<string, unknown> = {
      message,
      ...properties,
    };

    if (error instanceof Error) {
      errorProps['name'] = error.name;
      errorProps['stack'] = error.stack;
      // Preserve a clean message if not already overridden by caller
      if (!errorProps['message']) {
        errorProps['message'] = error.message;
      }
    } else if (error !== undefined && error !== null) {
      // Non-Error throwable (string, object, etc.)
      errorProps['thrown'] = String(error);
    }

    this.enqueueEvent('error', errorProps);
    this.sessionManager?.recordEvent();
  }

  pageView(page?: string, properties?: Record<string, unknown>): void {
    if (typeof window === 'undefined') return;
    const pageCtx = getPageContext();
    this.sessionManager?.recordPageView(pageCtx.url);
    this.enqueueEvent('page', {
      url: page ?? pageCtx.url, path: pageCtx.path,
      title: pageCtx.title, referrer: pageCtx.referrer, ...properties,
    });
  }

  conversion(event: string, value?: number, properties?: Record<string, unknown>): void {
    this.enqueueEvent('conversion', { event, value, ...properties });
    this.sessionManager?.recordEvent();
  }


  startJourney(nameOrType: string, properties?: JourneyPayload): CurrentJourney | null {
    const timestamp = now();
    const journey: CurrentJourney = {
      journeyId: String(properties?.journeyId ?? generateId()),
      journeyName: properties?.journeyName ?? nameOrType,
      journeyType: properties?.journeyType ?? nameOrType,
      journeyStatus: 'started',
      startedAt: timestamp,
      updatedAt: timestamp,
      ...properties,
    };
    this.currentJourney = journey;
    this.emitJourneyEvent('journey_started', journey);
    return this.currentJourney;
  }

  pauseJourney(reason?: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.lastJourneyPauseAt = Date.now();
    this.updateJourney('paused', { pauseReason: reason, ...properties });
    this.emitJourneyEvent('journey_paused', this.currentJourney);
  }

  resumeJourney(reason?: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) {
      this.currentJourney = {
        journeyId: properties?.journeyId ?? generateId(),
        journeyName: properties?.journeyName,
        journeyType: properties?.journeyType,
        journeyStatus: 'resumed',
        startedAt: now(),
        updatedAt: now(),
        ...properties,
      };
    }
    if (!this.currentJourney) return;
    const latency = this.lastJourneyPauseAt ? Date.now() - this.lastJourneyPauseAt : undefined;
    this.updateJourney('resumed', { resumeReason: reason, handoffLatencyMs: latency, ...properties });
    this.emitJourneyEvent('journey_resumed', this.currentJourney);
  }

  continueJourney(stepIdOrName: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.updateJourney('continued', { stepId: properties?.stepId ?? stepIdOrName, stepName: properties?.stepName ?? stepIdOrName, ...properties });
    this.emitJourneyEvent('journey_continued', this.currentJourney);
  }

  completeJourney(reason?: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.updateJourney('completed', { completionReason: reason, ...properties });
    this.emitJourneyEvent('journey_completed', this.currentJourney);
    this.currentJourney = null;
  }

  abandonJourney(reason?: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.updateJourney('abandoned', { abandonmentReason: reason, ...properties });
    this.emitJourneyEvent('journey_abandoned', this.currentJourney);
    this.currentJourney = null;
  }

  checkpointJourney(stepIdOrName: string, properties?: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.updateJourney('checkpoint', { stepId: properties?.stepId ?? stepIdOrName, stepName: properties?.stepName ?? stepIdOrName, ...properties });
    this.emitJourneyEvent('journey_checkpoint', this.currentJourney);
  }

  getCurrentJourney(): CurrentJourney | null {
    return this.currentJourney ? { ...this.currentJourney } : null;
  }

  onJourneyResumed(callback: (identity: ResolvedIdentity) => void): () => void {
    this.journeyResumeListeners.push(callback);
    return () => {
      this.journeyResumeListeners = this.journeyResumeListeners.filter((cb) => cb !== callback);
    };
  }

  hydrateIdentity(data: IdentityData): void {
    if (!this.identityManager) return;
    const priorUserId = this.identityManager.getUserId();
    const identity = this.identityManager.hydrateIdentity(data);
    this.enqueueEvent('identify', {
      userId: identity.userId, traits: identity.traits,
      walletAddress: identity.walletAddress,
      walletsCount: identity.wallets.length,
    });

    // Link wallets from identity data
    if (data.walletAddress && this.web3Module) {
      this.web3Module.connect(data.walletAddress, {
        type: data.walletType, chainId: data.chainId, ens: data.ens,
      });
    }

    if (data.wallets) {
      for (const w of data.wallets) {
        switch (w.vm) {
          case 'evm': this.web3Module?.connect(w.address, { type: w.walletType, chainId: w.chainId as number }); break;
          case 'svm': this.web3Module?.connectSVM(w.address, { type: w.walletType }); break;
          case 'bitcoin': this.web3Module?.connectBTC(w.address, { type: w.walletType }); break;
          case 'movevm': this.web3Module?.connectSUI(w.address, { type: w.walletType }); break;
          case 'near': this.web3Module?.connectNEAR(w.address, { type: w.walletType }); break;
          case 'tvm': this.web3Module?.connectTRON(w.address, { type: w.walletType }); break;
          case 'cosmos': this.web3Module?.connectCosmos(w.address, { type: w.walletType }); break;
          case 'aptos': this.web3Module?.connectAptos(w.address, { type: w.walletType }); break;
          case 'ton': this.web3Module?.connectTON(w.address, { type: w.walletType }); break;
          case 'starknet': this.web3Module?.connectStarknet(w.address, { type: w.walletType }); break;
          case 'cardano': this.web3Module?.connectCardano(w.address, { type: w.walletType }); break;
          case 'substrate': this.web3Module?.connectSubstrate(w.address, { type: w.walletType }); break;
          case 'algorand': this.web3Module?.connectAlgorand(w.address, { type: w.walletType }); break;
          case 'hedera': this.web3Module?.connectHedera(w.address, { type: w.walletType }); break;
          case 'stellar': this.web3Module?.connectStellar(w.address, { type: w.walletType }); break;
          case 'icp': this.web3Module?.connectICP(w.address, { type: w.walletType }); break;
        }
      }
    }

    // Cross-device: fire resolve when userId or email first becomes known (or changes).
    // Guard email with _lastEmailHash so repeated hydrateIdentity({ email }) calls
    // don't generate redundant network requests.
    if (this.config?.autoResumeJourney !== false) {
      const newUserId = identity.userId !== priorUserId ? identity.userId : undefined;
      if (newUserId || data.email) {
        this._hashEmail(data.email).then((emailHash) => {
          if (emailHash === this._lastEmailHash && !newUserId) return;
          if (emailHash !== undefined) this._lastEmailHash = emailHash;
          this.resolveIdentity({ wallets: identity.wallets, userId: newUserId, emailHash }).catch(() => {});
        });
      }
    }
  }

  getIdentity(): Identity | null {
    return this.identityManager?.getIdentity() ?? null;
  }

  reset(): void {
    this.flush();
    this.identityManager?.reset();
    this.sessionManager?.reset();
    this.web3Module?.disconnect();
    this._lastEmailHash = undefined;
    // A reset creates a fresh anonymous identity/session, so any in-flight
    // journey must be cleared too — otherwise the next checkpoint/complete
    // reuses the previous user's journeyId under the new identity and the
    // stitcher links two identities into one journey.
    this.currentJourney = null;
    this.lastJourneyPauseAt = null;
    this.log('info', 'SDK reset — new anonymous identity created');
  }

  async flush(): Promise<void> {
    await this.eventQueue?.flush();
  }

  destroy(): void {
    this.log('info', 'Destroying Aether SDK');
    this.healthAgentConsentUnsub?.();
    this.healthAgentConsentUnsub = null;
    this.healthAgent?.stop();
    this.healthAgent = null;
    // Clear remote manifest state so a subsequent init() for a different
    // tenant/key starts from defaults rather than the prior manifest's switches.
    this.remoteFeatures = {};
    this.flush();
    this.autoDiscovery?.destroy();
    this.consentModule?.destroy();
    this.web3Module?.destroy();
    this.sessionManager?.destroy();
    this.eventQueue?.destroy();
    this.performanceModule?.destroy();
    this.plugins.forEach((p) => { try { p.destroy(); } catch { /* */ } });

    this.semanticContext?.destroy();
    this.rewardClient?.destroy();
    this.ecommerceModule?.destroy();
    this.formAnalytics?.destroy();
    this.featureFlags?.destroy();
    this.heatmapModule?.destroy();
    this.funnelModule?.destroy();
    this.autoDiscovery = null;
    this.consentModule = null;
    this.web3Module = null;
    this.semanticContext = null;
    this.trafficTracker = null;
    this.fingerprintCollector = null;
    this.rewardClient = null;
    this.ecommerceModule = null;
    this.formAnalytics = null;
    this.featureFlags = null;
    this.heatmapModule = null;
    this.funnelModule = null;
    this.performanceModule = null;
    this.sessionManager = null;
    this.identityManager = null;
    this.eventQueue = null;
    this.config = null;
    this.plugins = [];
    this.walletChangeListeners = [];
    this.journeyResumeListeners = [];
    if (this.journeyVisibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.journeyVisibilityHandler);
    }
    this.journeyVisibilityHandler = null;
    this.currentJourney = null;
    this.lastJourneyPauseAt = null;
    this.initialized = false;
  }

  // =========================================================================
  // SUB-INTERFACES
  // =========================================================================

  wallet: WalletInterface = {
    connect: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connect(address, options);
    },
    connectSVM: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectSVM(address, options);
    },
    connectBTC: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectBTC(address, options);
    },
    connectSUI: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectSUI(address, options);
    },
    connectNEAR: (accountId: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectNEAR(accountId, options);
    },
    connectTRON: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectTRON(address, options);
    },
    connectCosmos: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectCosmos(address, options);
    },
    connectAptos: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectAptos(address, options);
    },
    connectTON: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectTON(address, options);
    },
    connectStarknet: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectStarknet(address, options);
    },
    connectCardano: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectCardano(address, options);
    },
    connectSubstrate: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectSubstrate(address, options);
    },
    connectAlgorand: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectAlgorand(address, options);
    },
    connectHedera: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectHedera(address, options);
    },
    connectStellar: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectStellar(address, options);
    },
    connectICP: (principal: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connectICP(principal, options);
    },
    disconnect: (address?: string) => {
      this.web3Module?.disconnect(address);
    },
    getInfo: (): WalletInfo | null => {
      return this.web3Module?.getInfo() ?? null;
    },
    getWallets: (): ConnectedWallet[] => {
      return this.identityManager?.getWallets() ?? [];
    },
    getWalletsByVM: (vm: VMType): ConnectedWallet[] => {
      return this.identityManager?.getWalletsByVM(vm) ?? [];
    },
    transaction: (txHash: string, options?: TransactionOptions) => {
      this.web3Module?.transaction(txHash, options);
    },
    onWalletChange: (callback: (wallets: ConnectedWallet[]) => void): (() => void) => {
      return this.web3Module?.onWalletChange(callback) ?? (() => {});
    },
  };

  // =========================================================================
  // COMMERCE / AGENT / x402 — thin canonical emitters
  // Backend owns workflow. SDK only records events.
  // =========================================================================

  commerce: CommerceInterface = {
    paymentInitiated: (props) => this.enqueueEvent('payment_initiated', props as Record<string, unknown>),
    paymentCompleted: (props) => this.enqueueEvent('payment_completed', props as Record<string, unknown>),
    paymentFailed: (props) => this.enqueueEvent('payment_failed', props as Record<string, unknown>),
    approvalRequested: (props) => this.enqueueEvent('approval_requested', props as Record<string, unknown>),
    approvalResolved: (props) => this.enqueueEvent('approval_resolved', props as Record<string, unknown>),
    entitlementGranted: (props) => this.enqueueEvent('entitlement_granted', props as Record<string, unknown>),
    entitlementRevoked: (props) => this.enqueueEvent('entitlement_revoked', props as Record<string, unknown>),
    accessGranted: (props) => this.enqueueEvent('access_granted', props as Record<string, unknown>),
    accessDenied: (props) => this.enqueueEvent('access_denied', props as Record<string, unknown>),
  };

  agent: AgentInterface = {
    // Lifecycle emitters — granular events
    registered: (props) => this.enqueueEvent('agent_registered', props as Record<string, unknown>),
    updated: (props) => this.enqueueEvent('agent_updated', props as Record<string, unknown>),
    authorized: (props) => this.enqueueEvent('agent_authorized', props as Record<string, unknown>),
    deauthorized: (props) => this.enqueueEvent('agent_deauthorized', props as Record<string, unknown>),
    capabilityGranted: (props) => this.enqueueEvent('agent_capability_granted', props as Record<string, unknown>),
    capabilityRevoked: (props) => this.enqueueEvent('agent_capability_revoked', props as Record<string, unknown>),
    taskCreated: (props) => this.enqueueEvent('agent_task_created', props as Record<string, unknown>),
    taskDecomposed: (props) => this.enqueueEvent('agent_task_decomposed', props as Record<string, unknown>),
    taskStarted: (props) => this.enqueueEvent('agent_task_started', props as Record<string, unknown>),
    taskCompleted: (props) => this.enqueueEvent('agent_task_completed', props as Record<string, unknown>),
    taskFailed: (props) => this.enqueueEvent('agent_task_failed', props as Record<string, unknown>),
    toolCalled: (props) => this.enqueueEvent('agent_tool_called', props as Record<string, unknown>),
    resourceRequested: (props) => this.enqueueEvent('agent_resource_requested', props as Record<string, unknown>),
    delegatedTask: (props) => this.enqueueEvent('agent_delegated_task', props as Record<string, unknown>),
    subagentSpawned: (props) => this.enqueueEvent('agent_subagent_spawned', props as Record<string, unknown>),
    policyEvaluated: (props) => this.enqueueEvent('agent_policy_evaluated', props as Record<string, unknown>),
    handoff: (props) => this.enqueueEvent('agent_handoff', props as Record<string, unknown>),
    escalatedToHuman: (props) => this.enqueueEvent('agent_escalated_to_human', props as Record<string, unknown>),
    outcomeRecorded: (props) => this.enqueueEvent('agent_outcome_recorded', props as Record<string, unknown>),
    // Legacy emitters — kept for backward compatibility
    task: (props) => this.enqueueEvent('agent_task', props as Record<string, unknown>),
    decision: (props) => this.enqueueEvent('agent_decision', props as Record<string, unknown>),
    interaction: (props) => this.enqueueEvent('a2h_interaction', props as Record<string, unknown>),
  };

  x402: X402Interface = {
    // Lifecycle emitters — granular events
    resourceRequested: (props) => this.enqueueEvent('x402_resource_requested', props as Record<string, unknown>),
    paymentRequired: (props) => this.enqueueEvent('x402_payment_required', props as Record<string, unknown>),
    quoteReceived: (props) => this.enqueueEvent('x402_quote_received', props as Record<string, unknown>),
    authorizationRequested: (props) => this.enqueueEvent('x402_authorization_requested', props as Record<string, unknown>),
    authorizationResolved: (props) => this.enqueueEvent('x402_authorization_resolved', props as Record<string, unknown>),
    paymentIntentCreated: (props) => this.enqueueEvent('x402_payment_intent_created', props as Record<string, unknown>),
    paymentSubmitted: (props) => this.enqueueEvent('x402_payment_submitted', props as Record<string, unknown>),
    paymentSettled: (props) => this.enqueueEvent('x402_payment_settled', props as Record<string, unknown>),
    paymentFailed: (props) => this.enqueueEvent('x402_payment_failed', props as Record<string, unknown>),
    paymentTimeout: (props) => this.enqueueEvent('x402_payment_timeout', props as Record<string, unknown>),
    receiptVerified: (props) => this.enqueueEvent('x402_receipt_verified', props as Record<string, unknown>),
    accessGranted: (props) => this.enqueueEvent('x402_access_granted', props as Record<string, unknown>),
    accessDenied: (props) => this.enqueueEvent('x402_access_denied', props as Record<string, unknown>),
    refundOrReversal: (props) => this.enqueueEvent('x402_refund_or_reversal', props as Record<string, unknown>),
    // Legacy emitter — kept for backward compatibility
    payment: (props) => this.enqueueEvent('x402_payment', props as Record<string, unknown>),
  };

  consent: ConsentInterface = {
    getState: (): ConsentState => {
      return this.consentModule?.getState() ?? {
        analytics: false,
        marketing: false,
        personalization: false,
        web3: false,
        agent: false,
        commerce: false,
        financial_activity: false,
        credit: false,
        location: false,
        updatedAt: '',
        policyVersion: '',
      };
    },
    grant: (purposes: ConsentPurpose[]) => { this.consentModule?.grant(purposes); },
    revoke: (purposes: ConsentPurpose[]) => { this.consentModule?.revoke(purposes); },
    showBanner: (config?: ConsentBannerConfig) => { this.consentModule?.showBanner(config); },
    hideBanner: () => { this.consentModule?.hideBanner(); },
    onUpdate: (callback: ConsentCallback): (() => void) => {
      return this.consentModule?.onUpdate(callback) ?? (() => {});
    },
  };

  // =========================================================================
  // REWARDS — Thin claim-only API
  // =========================================================================

  rewards = {
    checkEligibility: async (userId: string, rewardId: string): Promise<Record<string, unknown>> => {
      if (!this.rewardClient) throw new Error('Aether SDK: reward client not initialized');
      return this.rewardClient.checkEligibility(userId, rewardId);
    },
    getClaimPayload: async (userId: string, rewardId: string): Promise<Record<string, unknown>> => {
      if (!this.rewardClient) throw new Error('Aether SDK: reward client not initialized');
      return this.rewardClient.getClaimPayload(userId, rewardId);
    },
    submitClaim: async (txHash: string, rewardId: string): Promise<Record<string, unknown>> => {
      if (!this.rewardClient) throw new Error('Aether SDK: reward client not initialized');
      return this.rewardClient.submitClaim(txHash, rewardId);
    },
  };

  // =========================================================================
  // SUB-INTERFACES — Proxied
  // =========================================================================

  ecommerce = createModuleProxy<EcommerceModule>(() => this.ecommerceModule);
  featureFlag = createModuleProxy<FeatureFlagModule>(() => this.featureFlags);
  heatmap = createModuleProxy<HeatmapModule>(() => this.heatmapModule);
  funnel = createModuleProxy<FunnelModule>(() => this.funnelModule);
  forms = createModuleProxy<FormAnalyticsModule>(() => this.formAnalytics);

  // =========================================================================
  // EVENT LISTENERS
  // =========================================================================

  use(plugin: AetherPlugin): void {
    this.plugins.push(plugin);
    if (this.initialized) plugin.init(this);
  }

  // =========================================================================
  // BACKEND CONFIG — replaces UpdateManager
  // =========================================================================

  /** Stable per-install SDK instance id, persisted across reloads. */
  private getSdkInstanceId(): string {
    if (this.sdkInstanceId) return this.sdkInstanceId;
    const storageKey = 'aether_sdk_instance_id';
    try {
      if (typeof localStorage !== 'undefined') {
        const existing = localStorage.getItem(storageKey);
        if (existing) {
          this.sdkInstanceId = existing;
          return existing;
        }
        const generated = `web_${generateId()}`;
        localStorage.setItem(storageKey, generated);
        this.sdkInstanceId = generated;
        return generated;
      }
    } catch {
      // localStorage unavailable (SSR / privacy mode) — fall back to ephemeral id
    }
    this.sdkInstanceId = `web_${generateId()}`;
    return this.sdkInstanceId;
  }

  /**
   * Start the SDK health agent (fleet heartbeats + remote-config manifest).
   *
   * Honors privacy settings: skips entirely under DNT, and for opt-in
   * deployments (GDPR mode / opt-in cookie consent) waits until analytics
   * consent is granted before reporting any identity or metadata.
   */
  private startHealthAgent(): void {
    if (typeof window === 'undefined' || !this.config) return;

    if (this.config.privacy?.respectDNT && navigator.doNotTrack === '1') {
      this.log('info', 'Health agent disabled — Do Not Track is enabled');
      return;
    }

    const requiresOptIn =
      this.config.privacy?.gdprMode === true ||
      this.config.privacy?.cookieConsent === 'opt-in';

    if (requiresOptIn && !(this.consentModule?.hasConsent('analytics') ?? false)) {
      // Defer until the visitor grants analytics consent, then start once.
      this.healthAgentConsentUnsub = this.consentModule?.onUpdate(() => {
        if (this.consentModule?.hasConsent('analytics')) {
          this.launchHealthAgent();
        }
      }) ?? null;
      return;
    }

    this.launchHealthAgent();
  }

  /** Instantiate and start the health agent (idempotent). */
  private launchHealthAgent(): void {
    if (this.healthAgent || !this.config) return;
    // Consent satisfied (or not required) — stop listening for further changes.
    this.healthAgentConsentUnsub?.();
    this.healthAgentConsentUnsub = null;

    const endpoint = this.config.endpoint ?? DEFAULT_ENDPOINT;
    this.healthAgent = new SDKHealthAgent(
      {
        endpoint,
        apiKey: this.config.apiKey,
        sdkId: this.getSdkInstanceId(),
        appVersion: this.config.appVersion ?? '',
        platform: 'web',
        customHeaders: this.config.advanced?.customHeaders ?? {},
        getDynamicState: () => ({
          authValid: true,
          consentValid: this.consentModule?.hasConsent('analytics') ?? true,
          walletConnected: (this.identityManager?.getWallets().length ?? 0) > 0,
        }),
      },
      this.eventQueue!,
    );
    this.healthAgent.onManifestUpdate((manifest) => this.applyRemoteManifest(manifest));
    this.healthAgent.start();
  }

  /** Apply a remote-config manifest received from the backend to live modules. */
  private applyRemoteManifest(manifest: RemoteSDKManifest): void {
    if (manifest.features) {
      // Stored on the SDK itself so built-in analytics/web3/commerce emission is
      // gated even when the optional FeatureFlagModule is not enabled.
      this.remoteFeatures = { ...manifest.features };
      // Mirror into the cache-only flag module when the app opted into it.
      this.featureFlags?.applyManifestFeatures(manifest.features);
    }
    this.log('info', `Applied SDK manifest v${manifest.manifest_version}`);
  }

  /**
   * Built-in feature category an event belongs to, for remote-config gating.
   * Returns null for events not governed by a manifest feature switch.
   */
  private static featureForEvent(type: string): string | null {
    if (type.startsWith('agent_') || type === 'a2h_interaction') return 'agent';
    if (type.startsWith('payment_') || type.startsWith('approval_')
      || type.startsWith('entitlement_') || type.startsWith('access_')
      || type === 'x402_payment' || type === 'conversion') return 'commerce';
    if (type === 'wallet' || type === 'transaction' || type === 'contract_action') return 'web3';
    if (type === 'consent') return null; // never suppress consent signals
    return 'analytics';
  }

  /** Whether an event type is explicitly disabled by the active remote manifest. */
  private isRemotelyDisabled(type: string): boolean {
    const feature = AetherSDK.featureForEvent(type);
    return feature !== null && this.remoteFeatures[feature] === false;
  }

  /** Fetch configuration from backend (feature flags, funnel definitions, etc.) */
  private async fetchConfig(): Promise<void> {
    if (!this.config) return;
    const endpoint = this.config.endpoint ?? DEFAULT_ENDPOINT;

    try {
      const response = await fetch(`${endpoint}/v1/config`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${this.config.apiKey}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) return;

      const data = await response.json() as {
        featureFlags?: { key: string; enabled: boolean; value?: unknown }[];
        funnelDefinitions?: FunnelDefinition[];
      };

      // Load funnel definitions from backend
      if (data.funnelDefinitions && this.funnelModule) {
        this.funnelModule.loadDefinitions(data.funnelDefinitions);
      }

      this.log('debug', 'Remote config loaded');
    } catch {
      // Silent failure — local defaults will be used
    }
  }

  // =========================================================================
  // INIT HELPERS
  // =========================================================================

  private initCore(config: AetherConfig): void {
    this.identityManager = new IdentityManager();
    this.sessionManager = new SessionManager(
      config.advanced?.heartbeatInterval ?? 30000,
      (session) => this.enqueueEvent('heartbeat', { sessionDuration: session.lastActivityAt })
    );

    const endpoint = config.endpoint ?? DEFAULT_ENDPOINT;
    this.eventQueue = new EventQueue({
      endpoint,
      apiKey: config.apiKey,
      batchSize: config.advanced?.batchSize ?? 10,
      flushInterval: config.advanced?.flushInterval ?? 5000,
      maxQueueSize: config.advanced?.maxQueueSize ?? 100,
      retry: config.advanced?.retry,
      headers: config.advanced?.customHeaders ?? {},
      onError: (err) => this.log('error', 'Event send failed:', err.message),
      // Feed real ingestion metrics into the fleet-health heartbeat.
      onAttempt: (latencyMs, success) => this.healthAgent?.recordAttempt(latencyMs, success),
    });

    this.consentModule = new ConsentModule({
      purposes: ['analytics', 'marketing', 'web3'],
      policyUrl: '/privacy',
    });

    this.eventQueue.setConsent(this.consentModule.getState());
    this.consentModule.onUpdate((state) => {
      this.eventQueue?.setConsent(state);
      this.enqueueEvent('consent', { consent: state });
    });

    if (config.privacy?.gdprMode && !this.consentModule.hasRecordedConsent()) {
      this.consentModule.showBanner();
    }

    // Semantic context — Tier 1 only
    this.semanticContext = new SemanticContextCollector(SDK_VERSION);

    // Traffic source tracking — raw param shipping
    this.trafficTracker = new TrafficSourceTracker();
    this.trafficTracker.detect();

    // Device fingerprint (consent-gated)
    this.fingerprintCollector = new DeviceFingerprintCollector();
    this.fingerprintCollector.generate().catch(() => {});

    this.sessionManager.start();

    // Cross-device: resolve identity on init (fingerprint path for all users,
    // plus wallet path if prior wallets are cached)
    if (config.autoResumeJourney !== false) {
      const priorWallets = this.identityManager.getWallets();
      this.resolveIdentity({ wallets: priorWallets }).catch(() => {});
    }

    // Reward client — thin claim-only stub
    this.rewardClient = createRewardClient({
      endpoint,
      apiKey: config.apiKey,
    });
  }

  private initWeb3(config: AetherConfig, modules: NonNullable<AetherConfig['modules']>): void {
    if (modules.walletTracking || modules.svmTracking || modules.bitcoinTracking ||
        modules.moveTracking || modules.nearTracking || modules.tronTracking || modules.cosmosTracking ||
        modules.aptosTracking || modules.tonTracking || modules.starknetTracking ||
        modules.cardanoTracking || modules.substrateTracking || modules.algorandTracking ||
        modules.hederaTracking || modules.stellarTracking || modules.icpTracking) {
      this.web3Module = new Web3Module(
        {
          onWalletEvent: (action, data) => {
            this.enqueueEvent('wallet', { action, ...data });
            if (action === 'connect' && config.autoResumeJourney !== false) {
              const address = data['address'] as string | undefined;
              const vm = data['vm'] as VMType | undefined;
              if (address && vm) {
                this.resolveIdentity({ wallets: [{ address, vm }] }).catch(() => {});
              }
            }
          },
          onTransaction: (txHash, data) => this.enqueueEvent('transaction', { txHash, ...data }),
        },
        {
          walletTracking: modules.walletTracking,
          svmTracking: modules.svmTracking,
          bitcoinTracking: modules.bitcoinTracking,
          moveTracking: modules.moveTracking,
          nearTracking: modules.nearTracking,
          tronTracking: modules.tronTracking,
          cosmosTracking: modules.cosmosTracking,
          aptosTracking: modules.aptosTracking,
          tonTracking: modules.tonTracking,
          starknetTracking: modules.starknetTracking,
          cardanoTracking: modules.cardanoTracking,
          substrateTracking: modules.substrateTracking,
          algorandTracking: modules.algorandTracking,
          hederaTracking: modules.hederaTracking,
          stellarTracking: modules.stellarTracking,
          icpTracking: modules.icpTracking,
          cosmosChains: modules.cosmosChains,
          approvalScan: modules.approvalScan,
          domainResolution: modules.domainResolution,
          networkContext: modules.networkContext,
        }
      );
      this.web3Module.init();
    }
  }

  private initWeb2(config: AetherConfig, modules: NonNullable<AetherConfig['modules']>): void {
    const trackFn = (event: string, props?: Record<string, unknown>) => this.track(event, props);

    // E-commerce — thin stub
    if (modules.ecommerce !== false) {
      this.ecommerceModule = new EcommerceModule({ onTrack: trackFn });
    }

    // Form analytics — thin field emitter
    if (modules.formAnalytics !== false) {
      this.formAnalytics = new FormAnalyticsModule({ onTrack: trackFn }, {
        autoDiscover: true,
      });
    }

    // Feature flags — cache-only layer
    if (modules.featureFlags) {
      this.featureFlags = new FeatureFlagModule({ onTrack: trackFn });
      const endpoint = config.endpoint ?? DEFAULT_ENDPOINT;
      this.featureFlags.init({ endpoint, apiKey: config.apiKey }).catch(() => { /* silent */ });
    }

    // Heatmaps — thin coordinate emitter
    if (modules.heatmaps) {
      this.heatmapModule = new HeatmapModule({ onTrack: trackFn });
      this.heatmapModule.start();
    }

    // Funnels — thin event tagger
    if (modules.funnels) {
      this.funnelModule = new FunnelModule({ onTrack: trackFn });
    }

    // Performance — Web Vitals, Navigation Timing, Long Tasks, Memory
    if (modules.performance !== false) {
      const perfCfg = typeof modules.performance === 'object' ? modules.performance : {};
      this.performanceModule = new PerformanceModule({
        onTrack: trackFn,
        sampleRate: perfCfg.sampleRate ?? 1.0,
      });
      this.performanceModule.start();
    }
  }

  private initAnalytics(config: AetherConfig, modules: NonNullable<AetherConfig['modules']>): void {
    // Auto-discovery — minimal click tracker
    if (modules.autoDiscovery !== false) {
      this.autoDiscovery = new AutoDiscoveryModule(
        { onTrack: (event, props) => this.track(event, props) }
      );
      this.autoDiscovery.start();
    }
  }

  // =========================================================================
  // PRIVATE
  // =========================================================================

  private enqueueEvent(type: string, properties: Record<string, unknown>): void {
    if (!this.eventQueue || !this.identityManager || !this.sessionManager) return;

    // Honor remote-config feature switches published from the tenant fleet UI.
    if (this.isRemotelyDisabled(type)) {
      this.log('debug', `Event suppressed by remote manifest: ${type}`);
      return;
    }

    const session = this.sessionManager.getSession();
    const identity = this.identityManager.getIdentity();
    const consent = this.consentModule?.getState() ?? null;
    const semantic = this.semanticContext?.collect();

    const event = {
      id: generateId(),
      type,
      timestamp: now(),
      sessionId: session?.id ?? '',
      anonymousId: identity.anonymousId,
      userId: identity.userId,
      properties,
      context: {
        library: { name: '@aether/web', version: SDK_VERSION },
        page: typeof window !== 'undefined' ? getPageContext() : undefined,
        device: typeof window !== 'undefined' ? getDeviceContext() : undefined,
        campaign: typeof window !== 'undefined' ? getCampaignContext() : undefined,
        fingerprint: this.fingerprintCollector?.getFingerprintId()
          ? { id: this.fingerprintCollector.getFingerprintId()! }
          : undefined,
        locale: typeof navigator !== 'undefined' ? navigator.language : undefined,
        timezone: Intl?.DateTimeFormat?.()?.resolvedOptions?.()?.timeZone,
        consent,
        semantic,
        trafficSource: this.trafficTracker?.toEventPayload(),
        network: typeof navigator !== 'undefined' && (navigator as any).connection ? {
          effectiveType: (navigator as any).connection.effectiveType,
          downlink: (navigator as any).connection.downlink,
          rtt: (navigator as any).connection.rtt,
          saveData: (navigator as any).connection.saveData,
        } : undefined,
      },
    };

    this.eventQueue.enqueue(event as any);
    this.log('debug', `Event: ${type}`, properties);
  }


  private updateJourney(status: NonNullable<CurrentJourney['journeyStatus']>, properties: JourneyPayload): void {
    if (!this.currentJourney) return;
    this.currentJourney = {
      ...this.currentJourney,
      ...properties,
      journeyStatus: status,
      updatedAt: now(),
    };
  }

  private emitJourneyEvent(type: JourneyLifecycleEventType, properties: JourneyPayload): void {
    const payload: JourneyPayload = {
      ...properties,
      journeyStatus: properties.journeyStatus ?? type.replace('journey_', '') as JourneyPayload['journeyStatus'],
    };
    this.enqueueEvent(type, payload as Record<string, unknown>);
    this.sessionManager?.recordEvent();
  }

  private setupJourneyLifecycleTracking(): void {
    if (typeof document === 'undefined' || typeof window === 'undefined') return;
    // Remove a handler left by a prior init() so re-initialization (destroy()
    // then init()) does not stack duplicate listeners that each emit journey
    // pause/continue/abandon events on a single visibility change.
    if (this.journeyVisibilityHandler) {
      document.removeEventListener('visibilitychange', this.journeyVisibilityHandler);
    }
    this.journeyVisibilityHandler = () => {
      if (!this.currentJourney) return;
      if (document.visibilityState === 'hidden') {
        this.pauseJourney('page_hidden');
        return;
      }
      const timeout = this.config?.journeyTimeoutMs ?? 30 * 60 * 1000;
      if (this.lastJourneyPauseAt && Date.now() - this.lastJourneyPauseAt > timeout) {
        this.abandonJourney('client_inactivity_timeout');
      } else {
        this.continueJourney(this.currentJourney.stepId ?? this.currentJourney.stepName ?? 'foreground', { resumeReason: 'page_visible' });
      }
    };
    document.addEventListener('visibilitychange', this.journeyVisibilityHandler);
  }

  private async resolveIdentity(opts: {
    wallets?: { address: string; vm: VMType }[];
    userId?: string;
    emailHash?: string;
  }): Promise<void> {
    if (!this.config || !this.identityManager) return;

    const endpoint = this.config.endpoint ?? DEFAULT_ENDPOINT;
    const currentAnonymousId = this.identityManager.getAnonymousId();
    const fp = this.fingerprintCollector;
    const fpComponents = fp?.getComponents();

    const body = {
      wallets: (opts.wallets ?? []).map((w) => ({ address: w.address, vm: w.vm })),
      anonymous_id: currentAnonymousId,
      device_fingerprint: fp?.getFingerprintId() ?? null,
      fingerprint_signals: fpComponents ? {
        canvas_hash: fpComponents.canvasHash,
        webgl_renderer: fpComponents.webglRenderer,
        timezone: fpComponents.timezone,
        language: fpComponents.language,
      } : undefined,
      user_id: opts.userId ?? null,
      email_hash: opts.emailHash ?? null,
      platform: 'web',
    };

    let resolved: ResolvedIdentity | null = null;
    let rawIdentity: Record<string, unknown> | null = null;
    try {
      const res = await fetch(`${endpoint}/sdk/identity/resolve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': this.config.apiKey,
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) return;
      const data = await res.json() as { resolved: boolean; identity?: Record<string, unknown> };
      if (!data.resolved || !data.identity) return;

      // Map snake_case backend fields to camelCase TypeScript type
      const raw = data.identity;
      rawIdentity = raw;
      const rawWalletRefs = (raw.wallet_refs ?? []) as Array<{ address: string; vm: string }>;
      const resolvedAt = ((raw.resolved_at ?? raw.resolvedAt) as string) ?? '';
      const mapped: ResolvedIdentity = {
        anonymousId: ((raw.anonymous_id ?? raw.anonymousId) as string) ?? '',
        userId: (raw.user_id ?? raw.userId) as string | undefined,
        resolvedAt,
        wallets: rawWalletRefs.map((w) => ({
          address: w.address,
          vm: w.vm as import('./types').VMType,
          chainId: '',
          walletType: 'unknown',
          displayName: w.address,
          classification: 'hot' as import('./types').WalletClassification,
          connectedAt: resolvedAt,
          isConnected: false,
          isPrimary: false,
        })),
      };
      if (mapped.anonymousId && mapped.anonymousId !== currentAnonymousId) {
        resolved = mapped;
      }
    } catch {
      return;
    }

    if (!resolved) return;

    this.identityManager.hydrateIdentity({
      userId: resolved.userId,
      traits: resolved.traits as Record<string, string> | undefined,
      wallets: resolved.wallets,
    });

    this.resumeJourney('identity_resolved', {
      sourceAnonymousId: resolved.anonymousId,
      targetAnonymousId: currentAnonymousId,
      targetUserId: resolved.userId,
      confidence: typeof rawIdentity?.confidence === 'number' ? rawIdentity.confidence : undefined,
      confidenceSignals: Array.isArray(rawIdentity?.confidence_signals) ? rawIdentity.confidence_signals as string[] : undefined,
      metadata: { resolvedUserId: resolved.userId ?? null },
    });

    this.log('info', 'Journey resumed from prior device');
    this.config.onJourneyResumed?.(resolved);
    for (const callback of this.journeyResumeListeners) {
      try { callback(resolved); } catch { /* listener errors are isolated */ }
    }
  }

  private async _hashEmail(email?: string): Promise<string | undefined> {
    if (!email || typeof crypto === 'undefined' || !crypto.subtle) return undefined;
    try {
      const normalized = email.toLowerCase().trim();
      const data = new TextEncoder().encode(normalized);
      const hashBuffer = await crypto.subtle.digest('SHA-256', data);
      return Array.from(new Uint8Array(hashBuffer)).map((b) => b.toString(16).padStart(2, '0')).join('');
    } catch {
      return undefined;
    }
  }

  private setupSPATracking(): void {
    if (typeof window === 'undefined') return;
    const checkpoint = () => {
      if (!this.currentJourney) return;
      const path = window.location.pathname + window.location.search;
      if (path === this.lastRouteCheckpointPath) return;
      this.lastRouteCheckpointPath = path;
      this.checkpointJourney(path, { stepName: document.title || path, metadata: { source: 'spa_route' } });
    };
    const onRoute = () => { this.pageView(); checkpoint(); };
    const origPush = history.pushState;
    const origReplace = history.replaceState;
    history.pushState = (...args) => { origPush.apply(history, args); setTimeout(onRoute, 0); };
    history.replaceState = (...args) => { origReplace.apply(history, args); setTimeout(onRoute, 0); };
    window.addEventListener('popstate', () => { setTimeout(onRoute, 0); });
  }

  private log(level: 'debug' | 'info' | 'warn' | 'error', ...args: unknown[]): void {
    if (!this.debug && level === 'debug') return;
    const prefix = `[Aether SDK]`;
    switch (level) {
      case 'debug': console.debug(prefix, ...args); break;
      case 'info': console.info(prefix, ...args); break;
      case 'warn': console.warn(prefix, ...args); break;
      case 'error': console.error(prefix, ...args); break;
    }
  }
}

// =============================================================================
// SINGLETON EXPORT
// =============================================================================

const aether = new AetherSDK();

export default aether;
export { AetherSDK };
export type { AetherConfig, AetherSDKInterface, ResolvedIdentity, JourneyPayload, CurrentJourney, JourneyStatus, JourneyLifecycleEventType, AcquisitionEvidence, CampaignContext } from './types';
// AcquisitionEvidence and CampaignContext were added in the campaign registry milestone.
export { SDKHealthAgent } from './health';
export type { SDKHealthAgentConfig, SDKHeartbeatPayload, SDKManifest, ManifestUpdateCallback } from './health';
