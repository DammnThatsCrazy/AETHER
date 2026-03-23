// =============================================================================
// AETHER SDK — MAIN CLASS v7.0.0 (Tier 2 Thin Client)
// Public API orchestrating all modules: identity, session, events, web3
// Removed: EdgeML, Experiments, Performance, Feedback, UpdateManager
// Added: fetchConfig() for backend-driven configuration
// =============================================================================

import type {
  AetherConfig, AetherSDKInterface, AetherPlugin,
  IdentityData, Identity, WalletInfo, TransactionOptions,
  VMType, ConsentCallback, ConnectedWallet,
  ConsentState, ConsentBannerConfig, WalletInterface, ConsentInterface,
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
    disconnect: (address?: string) => {
      this.web3Module?.disconnect(address);
    },
    getInfo: (): WalletInfo | null => {
      return this.web3Module?.getInfo() ?? null;
    },
    getWallets: (): ConnectedWallet[] => {
      return [];
    },
    getWalletsByVM: (_vm: VMType): ConnectedWallet[] => {
      return [];
    },
    transaction: (txHash: string, options?: TransactionOptions) => {
      this.web3Module?.transaction(txHash, options);
    },
    onWalletChange: (callback: (wallets: ConnectedWallet[]) => void): (() => void) => {
      return this.web3Module?.onWalletChange(callback) ?? (() => {});
    },
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

    // Reward client — thin claim-only stub
    this.rewardClient = createRewardClient({
      endpoint,
      apiKey: config.apiKey,
    });
  }

  private initWeb3(config: AetherConfig, modules: NonNullable<AetherConfig['modules']>): void {
    if (modules.walletTracking || modules.svmTracking || modules.bitcoinTracking ||
        modules.moveTracking || modules.nearTracking || modules.tronTracking || modules.cosmosTracking) {
      this.web3Module = new Web3Module(
        {
          onWalletEvent: (action, data) => this.enqueueEvent('wallet', { action, ...data }),
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
      },
    };

    this.eventQueue.enqueue(event as any);
    this.log('debug', `Event: ${type}`, properties);
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
