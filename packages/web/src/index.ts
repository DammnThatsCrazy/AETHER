// =============================================================================
// AETHER SDK — MAIN CLASS v5.0.0
// Public API orchestrating all modules: identity, session, events, ML, web3
// Multi-VM Web3 support: EVM, Solana, Bitcoin, SUI, NEAR, TRON, Cosmos
// =============================================================================

import type {
  AetherConfig, AetherSDKInterface, AetherPlugin,
  IdentityData, Identity, WalletInfo, TransactionOptions,
  IntentVector, BotScore, SessionScore, VMType,
  IntentCallback, BotCallback, SessionCallback, ConsentCallback,
  ExperimentConfig, ExperimentAssignment, ConnectedWallet,
  ConsentState, ConsentBannerConfig, WalletInterface, ExperimentInterface, ConsentInterface,
  PortfolioSnapshot, WalletClassification,
} from './types';
import { EventQueue } from './core/event-queue';
import { SessionManager } from './core/session';
import { IdentityManager } from './core/identity';
import { AutoDiscoveryModule } from './modules/auto-discovery';
import { PerformanceModule } from './modules/performance';
import { ExperimentsModule } from './modules/experiments';
import { ConsentModule } from './consent';
import { Web3Module } from './web3';
import { EdgeMLModule } from './ml/edge-ml';
import { UpdateManager } from './core/update-manager';
import { SemanticContextCollector } from './context/semantic-context';
import { TrafficSourceTracker } from './tracking/traffic-source-tracker';
import { setRemoteData as setChainRemoteData } from './web3/chains/chain-registry';
import { setRemoteData as setProtocolRemoteData } from './web3/defi/protocol-registry';
import { setRemoteData as setLabelRemoteData } from './web3/wallet/wallet-labels';
import { setRemoteData as setClassifierRemoteData } from './web3/wallet/wallet-classifier';
import { generateId, now, getPageContext, getDeviceContext, getCampaignContext } from './utils';

const SDK_VERSION = '5.0.0';
const DEFAULT_ENDPOINT = 'https://api.aether.network';

class AetherSDK implements AetherSDKInterface {
  private config: AetherConfig | null = null;
  private eventQueue: EventQueue | null = null;
  private sessionManager: SessionManager | null = null;
  private identityManager: IdentityManager | null = null;
  private autoDiscovery: AutoDiscoveryModule | null = null;
  private performanceModule: PerformanceModule | null = null;
  private experimentsModule: ExperimentsModule | null = null;
  private consentModule: ConsentModule | null = null;
  private web3Module: Web3Module | null = null;
  private edgeML: EdgeMLModule | null = null;
  private updateManager: UpdateManager | null = null;
  private semanticContext: SemanticContextCollector | null = null;
  private trafficTracker: TrafficSourceTracker | null = null;
  private plugins: AetherPlugin[] = [];
  private initialized = false;
  private debug = false;

  // Callback registries
  private intentCallbacks: IntentCallback[] = [];
  private botCallbacks: BotCallback[] = [];
  private sessionScoreCallbacks: SessionCallback[] = [];
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

    // Core managers
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

    // Consent module
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

    // Semantic context — tiered enrichment for all events
    this.semanticContext = new SemanticContextCollector(SDK_VERSION, {
      maxTier: config.privacy?.vectorizeData ? 1 : 3,
    });

    // Traffic source tracking — zero-config, auto-detect all sources
    this.trafficTracker = new TrafficSourceTracker();
    const detectedSource = this.trafficTracker.detect();
    this.log('debug', 'Traffic source detected:', detectedSource.source, '/', detectedSource.medium);

    // Start session
    this.sessionManager.start();

    // Initialize optional modules
    const modules = config.modules ?? {};

    // Auto-discovery
    if (modules.autoDiscovery !== false) {
      this.autoDiscovery = new AutoDiscoveryModule(
        { onTrack: (event, props) => this.track(event, props) },
        { maskSensitive: config.privacy?.maskSensitiveFields ?? true, piiPatterns: config.privacy?.piiPatterns }
      );
      this.autoDiscovery.start({
        clicks: true,
        forms: modules.formTracking !== false,
        scrollDepth: modules.scrollDepth !== false,
        rageClicks: modules.rageClickDetection !== false,
        deadClicks: modules.deadClickDetection !== false,
      });
    }

    // Performance tracking
    if (modules.performanceTracking) {
      this.performanceModule = new PerformanceModule({
        onPerformance: (metrics) => this.enqueueEvent('performance', metrics),
        onError: (error) => this.enqueueEvent('error', error),
      });
      this.performanceModule.start({ webVitals: true, errors: modules.errorTracking !== false });
    } else if (modules.errorTracking) {
      this.performanceModule = new PerformanceModule({
        onPerformance: () => {},
        onError: (error) => this.enqueueEvent('error', error),
      });
      this.performanceModule.start({ webVitals: false, errors: true });
    }

    // Experiments
    if (modules.experiments !== false) {
      this.experimentsModule = new ExperimentsModule(
        this.identityManager.getAnonymousId(),
        { onExposure: (expId, variant) => this.track('experiment_exposure', { experimentId: expId, variantId: variant }) }
      );
    }

    // Web3 — Multi-VM initialization
    if (modules.walletTracking || modules.svmTracking || modules.bitcoinTracking ||
        modules.moveTracking || modules.nearTracking || modules.tronTracking || modules.cosmosTracking) {
      this.web3Module = new Web3Module(
        {
          onWalletEvent: (action, data) => this.enqueueEvent('wallet', { action, ...data }),
          onTransaction: (txHash, data) => this.enqueueEvent('transaction', { txHash, ...data }),
          onTokenBalance: (balance) => this.enqueueEvent('token_balance', { ...balance }),
          onNFTDetected: (nft) => this.enqueueEvent('nft_detection', { ...nft }),
          onGasAnalytics: (gas) => this.enqueueEvent('track', { event: 'gas_analytics', ...gas }),
          onWhaleAlert: (alert) => this.enqueueEvent('whale_alert', { ...alert }),
          onDeFiInteraction: (data) => this.enqueueEvent('defi_interaction', data),
          onPortfolioUpdate: (snapshot) => this.enqueueEvent('portfolio_update', { ...snapshot }),
        },
        {
          walletTracking: modules.walletTracking,
          svmTracking: modules.svmTracking,
          bitcoinTracking: modules.bitcoinTracking,
          moveTracking: modules.moveTracking,
          nearTracking: modules.nearTracking,
          tronTracking: modules.tronTracking,
          cosmosTracking: modules.cosmosTracking,
          tokenTracking: modules.tokenTracking,
          nftDetection: modules.nftDetection,
          gasTracking: modules.gasTracking,
          whaleAlerts: modules.whaleAlerts,
          defiTracking: modules.defiTracking,
          portfolioTracking: modules.portfolioTracking,
          walletClassification: modules.walletClassification,
          perpetualsTracking: modules.perpetualsTracking,
          bridgeTracking: modules.bridgeTracking,
          cexTracking: modules.cexTracking,
        }
      );
      this.web3Module.init();
    }

    // Edge ML
    if (modules.intentPrediction || modules.predictiveAnalytics) {
      this.edgeML = new EdgeMLModule({
        onIntentPrediction: (intent) => {
          this.semanticContext?.setIntent(intent);
          this.intentCallbacks.forEach((cb) => { try { cb(intent); } catch { /* */ } });
          if (modules.predictiveAnalytics) {
            this.enqueueEvent('track', { event: 'intent_prediction', ...intent });
          }
        },
        onBotDetection: (score) => {
          this.botCallbacks.forEach((cb) => { try { cb(score); } catch { /* */ } });
        },
        onSessionScore: (score) => {
          this.semanticContext?.setSessionScore(score);
          this.sessionScoreCallbacks.forEach((cb) => { try { cb(score); } catch { /* */ } });
        },
      });
      this.edgeML.start(5000);
    }

    this.pageView();
    this.setupSPATracking();

    if (config.privacy?.respectDNT && navigator.doNotTrack === '1') {
      this.log('info', 'DNT detected — limiting data collection');
    }

    // Auto-update — OTA data module sync (non-blocking, fire-and-forget)
    const autoUpdate = config.autoUpdate ?? {};
    if (autoUpdate.enabled !== false) {
      const cdnEndpoint = config.endpoint?.replace('/api.', '/cdn.') ?? 'https://cdn.aether.network';
      this.updateManager = new UpdateManager(
        cdnEndpoint,
        SDK_VERSION,
        {
          enabled: true,
          checkIntervalMs: autoUpdate.checkIntervalMs,
          onUpdateAvailable: autoUpdate.onUpdateAvailable,
        },
        this.debug,
      );

      // Register data module injectors
      this.updateManager.registerInjector('chainRegistry', (data) => setChainRemoteData(data as any));
      this.updateManager.registerInjector('protocolRegistry', (data) => setProtocolRemoteData(data as any));
      this.updateManager.registerInjector('walletLabels', (data) => setLabelRemoteData(data as any));
      this.updateManager.registerInjector('walletClassification', (data) => setClassifierRemoteData(data as any));

      // Load cached data modules first (sync, instant)
      this.updateManager.loadCachedModules();

      // Start background update check (async, non-blocking)
      this.updateManager.start();
    }

    this.initialized = true;
    this.log('info', 'Aether SDK v5.0.0 initialized — Multi-VM Web3 + auto-update enabled');
  }

  track(event: string, properties?: Record<string, unknown>): void {
    this.enqueueEvent('track', { event, ...properties });
    this.sessionManager?.recordEvent();
  }

  pageView(page?: string, properties?: Record<string, unknown>): void {
    if (typeof window === 'undefined') return;
    const pageCtx = getPageContext();
    this.sessionManager?.recordPageView(pageCtx.url);
    this.semanticContext?.recordScreen(pageCtx.path);
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

    // Link additional wallets
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

    if (this.experimentsModule) {
      this.experimentsModule.setAnonymousId(identity.anonymousId);
    }
  }

  getIdentity(): Identity | null {
    return this.identityManager?.getIdentity() ?? null;
  }

  reset(): void {
    this.flush();
    this.identityManager?.reset();
    this.sessionManager?.reset();
    this.experimentsModule?.reset();
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
    this.performanceModule?.destroy();
    this.consentModule?.destroy();
    this.web3Module?.destroy();
    this.edgeML?.destroy();
    this.updateManager?.destroy();
    this.sessionManager?.destroy();
    this.eventQueue?.destroy();
    this.plugins.forEach((p) => { try { p.destroy(); } catch { /* */ } });

    this.semanticContext?.destroy();
    this.autoDiscovery = null;
    this.performanceModule = null;
    this.experimentsModule = null;
    this.consentModule = null;
    this.web3Module = null;
    this.edgeML = null;
    this.updateManager = null;
    this.semanticContext = null;
    this.trafficTracker = null;
    this.sessionManager = null;
    this.identityManager = null;
    this.eventQueue = null;
    this.config = null;
    this.plugins = [];
    this.intentCallbacks = [];
    this.botCallbacks = [];
    this.sessionScoreCallbacks = [];
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
      return this.web3Module?.getWallets() ?? [];
    },
    getWalletsByVM: (vm: VMType): ConnectedWallet[] => {
      return this.web3Module?.getWalletsByVM(vm) ?? [];
    },
    transaction: (txHash: string, options?: TransactionOptions) => {
      this.web3Module?.transaction(txHash, options);
    },
    getPortfolio: (): PortfolioSnapshot | null => {
      return this.web3Module?.getPortfolio() ?? null;
    },
    onWalletChange: (callback: (wallets: ConnectedWallet[]) => void): (() => void) => {
      return this.web3Module?.onWalletChange(callback) ?? (() => {});
    },
    classifyWallet: (address: string, vm: VMType): WalletClassification => {
      return this.web3Module?.classifyWalletAddress(address, vm) ?? 'hot';
    },
  };

  experiments: ExperimentInterface = {
    run: (config: ExperimentConfig): string => {
      return this.experimentsModule?.run(config) ?? Object.keys(config.variants)[0];
    },
    getAssignment: (experimentId: string): ExperimentAssignment | null => {
      return this.experimentsModule?.getAssignment(experimentId) ?? null;
    },
  };

  consent: ConsentInterface = {
    getState: (): ConsentState => {
      return this.consentModule?.getState() ?? { analytics: false, marketing: false, web3: false, updatedAt: '', policyVersion: '' };
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
  // EVENT LISTENERS
  // =========================================================================

  onIntentPrediction(callback: IntentCallback): () => void {
    this.intentCallbacks.push(callback);
    return () => { this.intentCallbacks = this.intentCallbacks.filter((cb) => cb !== callback); };
  }

  onBotDetection(callback: BotCallback): () => void {
    this.botCallbacks.push(callback);
    return () => { this.botCallbacks = this.botCallbacks.filter((cb) => cb !== callback); };
  }

  onSessionScore(callback: SessionCallback): () => void {
    this.sessionScoreCallbacks.push(callback);
    return () => { this.sessionScoreCallbacks = this.sessionScoreCallbacks.filter((cb) => cb !== callback); };
  }

  use(plugin: AetherPlugin): void {
    this.plugins.push(plugin);
    if (this.initialized) plugin.init(this);
  }

  // =========================================================================
  // PRIVATE
  // =========================================================================

  private enqueueEvent(type: string, properties: Record<string, unknown>): void {
    if (!this.eventQueue || !this.identityManager || !this.sessionManager) return;

    const session = this.sessionManager.getSession();
    const identity = this.identityManager.getIdentity();
    const consent = this.consentModule?.getState() ?? null;

    // Collect tiered semantic context
    const semantic = this.semanticContext?.collect(consent);

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
