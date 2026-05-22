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
  ConsentState, ConsentBannerConfig, WalletInterface, ConsentInterface,
  CommerceInterface, AgentInterface, X402Interface,
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
import { generateId, now, getPageContext, getDeviceContext, getCampaignContext } from './utils';
import { createModuleProxy } from './utils/module-proxy';

const SDK_VERSION = '7.0.0';
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

    if (config.privacy?.respectDNT && navigator.doNotTrack === '1') {
      this.log('info', 'DNT detected — limiting data collection');
    }

    this.initialized = true;
    this.log('info', 'Aether SDK v7.0.0 initialized — Tier 2 thin client');
  }

  track(event: string, properties?: Record<string, unknown>): void {
    this.enqueueEvent('track', { event, ...properties });
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

  hydrateIdentity(data: IdentityData): void {
    if (!this.identityManager) return;
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
  }

  getIdentity(): Identity | null {
    return this.identityManager?.getIdentity() ?? null;
  }

  reset(): void {
    this.flush();
    this.identityManager?.reset();
    this.sessionManager?.reset();
    this.web3Module?.disconnect();
    this.log('info', 'SDK reset — new anonymous identity created');
  }

  async flush(): Promise<void> {
    await this.eventQueue?.flush();
  }

  destroy(): void {
    this.log('info', 'Destroying Aether SDK');
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
    task: (props) => this.enqueueEvent('agent_task', props as Record<string, unknown>),
    decision: (props) => this.enqueueEvent('agent_decision', props as Record<string, unknown>),
    interaction: (props) => this.enqueueEvent('a2h_interaction', props as Record<string, unknown>),
  };

  x402: X402Interface = {
    payment: (props) => this.enqueueEvent('x402_payment', props as Record<string, unknown>),
  };

  consent: ConsentInterface = {
    getState: (): ConsentState => {
      return this.consentModule?.getState() ?? {
        analytics: false,
        marketing: false,
        web3: false,
        agent: false,
        commerce: false,
        updatedAt: '',
        policyVersion: '',
      };
    },
    grant: (purposes: string[]) => { this.consentModule?.grant(purposes); },
    revoke: (purposes: string[]) => { this.consentModule?.revoke(purposes); },
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

    // Cross-device: resolve identity for wallets carried over from a prior session
    if (config.autoResumeJourney !== false) {
      const priorWallets = this.identityManager.getWallets();
      if (priorWallets.length > 0) {
        this.checkWalletIdentityResolution(priorWallets).catch(() => {});
      }
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
                this.checkWalletIdentityResolution([{ address, vm }]).catch(() => {});
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
        library: { name: '@aether/sdk', version: SDK_VERSION },
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

  private async checkWalletIdentityResolution(wallets: { address: string; vm: VMType }[]): Promise<void> {
    if (!this.config || !this.identityManager) return;

    const endpoint = this.config.endpoint ?? DEFAULT_ENDPOINT;
    const currentAnonymousId = this.identityManager.getIdentity().anonymousId;

    const body = {
      wallets: wallets.map((w) => ({ address: w.address, vm: w.vm })),
      anonymousId: currentAnonymousId,
      fingerprint: this.fingerprintCollector?.getFingerprintId() ?? null,
    };

    let resolved: ResolvedIdentity | null = null;
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
      const data = await res.json() as { resolved: boolean; identity?: ResolvedIdentity };
      if (!data.resolved || !data.identity) return;

      // Resolved identity is from a different anonymous session — merge it
      if (data.identity.anonymousId !== currentAnonymousId) {
        resolved = data.identity;
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

    this.enqueueEvent('journey_resumed', {
      resolvedAnonymousId: resolved.anonymousId,
      resolvedUserId: resolved.userId ?? null,
    });

    this.log('info', 'Journey resumed from prior device via wallet resolution');
    this.config.onJourneyResumed?.(resolved);
  }

  private setupSPATracking(): void {
    if (typeof window === 'undefined') return;
    const origPush = history.pushState;
    const origReplace = history.replaceState;
    history.pushState = (...args) => { origPush.apply(history, args); setTimeout(() => this.pageView(), 0); };
    history.replaceState = (...args) => { origReplace.apply(history, args); setTimeout(() => this.pageView(), 0); };
    window.addEventListener('popstate', () => { setTimeout(() => this.pageView(), 0); });
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
export type { AetherConfig, AetherSDKInterface } from './types';
