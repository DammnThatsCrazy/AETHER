// =============================================================================
// AETHER SDK — MAIN CLASS
// Public API orchestrating all modules: identity, session, events, ML, web3
// =============================================================================

import type {
  AetherConfig, AetherSDKInterface, AetherPlugin,
  IdentityData, Identity, WalletInfo, TransactionOptions,
  IntentVector, BotScore, SessionScore,
  IntentCallback, BotCallback, SessionCallback, ConsentCallback,
  ExperimentConfig, ExperimentAssignment,
  ConsentState, ConsentBannerConfig, WalletInterface, ExperimentInterface, ConsentInterface,
} from './WebSDKTypes(CoreTypeDefinitions)';
import { EventQueue } from './CoreEventQueue';
import { SessionManager } from './CoreSessionManager';
import { IdentityManager } from './CoreIdentityManager';
import { AutoDiscoveryModule } from './AutoDiscoveryModule';
import { PerformanceModule } from './PerformanceModule';
import { ExperimentsModule } from './ExperimentModule';
import { ConsentModule } from './ConsentModule';
import { Web3Module } from './Web3Module';
import { EdgeMLModule } from './EdgeMLModule';
import { generateId, now, getPageContext, getDeviceContext, getCampaignContext } from './SDKUtilityFunctions';

const SDK_VERSION = '8.7.0';
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
  private plugins: AetherPlugin[] = [];
  private initialized = false;
  private debug = false;

  // Callback registries
  private intentCallbacks: IntentCallback[] = [];
  private botCallbacks: BotCallback[] = [];
  private sessionScoreCallbacks: SessionCallback[] = [];

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  /** Initialize the SDK with configuration */
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

    // Wire consent to event queue
    this.eventQueue.setConsent(this.consentModule.getState());
    this.consentModule.onUpdate((state) => {
      this.eventQueue?.setConsent(state);
      this.enqueueEvent('consent', { consent: state });
    });

    // GDPR mode: show banner if no consent recorded
    if (config.privacy?.gdprMode && !this.consentModule.hasRecordedConsent()) {
      this.consentModule.showBanner();
    }

    // Start session
    this.sessionManager.start();

    // Initialize optional modules
    const modules = config.modules ?? {};

    // Auto-discovery (clicks, forms, scroll, rage clicks, dead clicks)
    if (modules.autoDiscovery !== false) {
      this.autoDiscovery = new AutoDiscoveryModule(
        { onTrack: (event, props) => this.track(event, props) },
        {
          maskSensitive: config.privacy?.maskSensitiveFields ?? true,
          piiPatterns: config.privacy?.piiPatterns,
        }
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
      this.performanceModule.start({
        webVitals: true,
        errors: modules.errorTracking !== false,
      });
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

    // Web3
    if (modules.walletTracking) {
      this.web3Module = new Web3Module({
        onWalletEvent: (action, data) => this.enqueueEvent('wallet', { action, ...data }),
        onTransaction: (txHash, data) => this.enqueueEvent('transaction', { txHash, ...data }),
      });
      this.web3Module.init();
    }

    // Edge ML
    if (modules.intentPrediction || modules.predictiveAnalytics) {
      this.edgeML = new EdgeMLModule({
        onIntentPrediction: (intent) => {
          this.intentCallbacks.forEach((cb) => { try { cb(intent); } catch { /* */ } });
          if (modules.predictiveAnalytics) {
            this.enqueueEvent('track', { event: 'intent_prediction', ...intent });
          }
        },
        onBotDetection: (score) => {
          this.botCallbacks.forEach((cb) => { try { cb(score); } catch { /* */ } });
        },
        onSessionScore: (score) => {
          this.sessionScoreCallbacks.forEach((cb) => { try { cb(score); } catch { /* */ } });
        },
      });
      this.edgeML.start(5000);
    }

    // Track initial page view
    this.pageView();

    // Track page navigation (SPA support)
    this.setupSPATracking();

    // Track DNT
    if (config.privacy?.respectDNT && navigator.doNotTrack === '1') {
      this.log('info', 'DNT detected — limiting data collection');
    }

    this.initialized = true;
    this.log('info', 'Aether SDK initialized successfully');
  }

  /** Track a custom event */
  track(event: string, properties?: Record<string, unknown>): void {
    this.enqueueEvent('track', { event, ...properties });
    this.sessionManager?.recordEvent();
  }

  /** Track a page view */
  pageView(page?: string, properties?: Record<string, unknown>): void {
    if (typeof window === 'undefined') return;
    const pageCtx = getPageContext();
    this.sessionManager?.recordPageView(pageCtx.url);
    this.enqueueEvent('page', {
      url: page ?? pageCtx.url,
      path: pageCtx.path,
      title: pageCtx.title,
      referrer: pageCtx.referrer,
      ...properties,
    });
  }

  /** Track a conversion event */
  conversion(event: string, value?: number, properties?: Record<string, unknown>): void {
    this.enqueueEvent('conversion', { event, value, ...properties });
    this.sessionManager?.recordEvent();
  }

  /** Hydrate identity with known user data */
  hydrateIdentity(data: IdentityData): void {
    if (!this.identityManager) return;
    const identity = this.identityManager.hydrateIdentity(data);
    this.enqueueEvent('identify', {
      userId: identity.userId,
      traits: identity.traits,
      walletAddress: identity.walletAddress,
    });

    // Update wallet module if wallet provided
    if (data.walletAddress && this.web3Module) {
      this.web3Module.connect(data.walletAddress, {
        type: data.walletType,
        chainId: data.chainId,
        ens: data.ens,
      });
    }

    // Update experiments module with new identity
    if (this.experimentsModule) {
      this.experimentsModule.setAnonymousId(identity.anonymousId);
    }
  }

  /** Get current identity */
  getIdentity(): Identity | null {
    return this.identityManager?.getIdentity() ?? null;
  }

  /** Reset — clear identity, session, and start fresh */
  reset(): void {
    this.flush();
    this.identityManager?.reset();
    this.sessionManager?.reset();
    this.experimentsModule?.reset();
    this.web3Module?.disconnect();
    this.log('info', 'SDK reset — new anonymous identity created');
  }

  /** Flush all queued events immediately */
  async flush(): Promise<void> {
    await this.eventQueue?.flush();
  }

  /** Destroy the SDK and clean up all resources */
  destroy(): void {
    this.log('info', 'Destroying Aether SDK');
    this.flush();
    this.autoDiscovery?.destroy();
    this.performanceModule?.destroy();
    this.consentModule?.destroy();
    this.web3Module?.destroy();
    this.edgeML?.destroy();
    this.sessionManager?.destroy();
    this.eventQueue?.destroy();
    this.plugins.forEach((p) => { try { p.destroy(); } catch { /* */ } });

    this.autoDiscovery = null;
    this.performanceModule = null;
    this.experimentsModule = null;
    this.consentModule = null;
    this.web3Module = null;
    this.edgeML = null;
    this.sessionManager = null;
    this.identityManager = null;
    this.eventQueue = null;
    this.config = null;
    this.plugins = [];
    this.intentCallbacks = [];
    this.botCallbacks = [];
    this.sessionScoreCallbacks = [];
    this.initialized = false;
  }

  // =========================================================================
  // SUB-INTERFACES
  // =========================================================================

  wallet: WalletInterface = {
    connect: (address: string, options?: Partial<WalletInfo>) => {
      this.web3Module?.connect(address, options);
    },
    disconnect: () => {
      this.web3Module?.disconnect();
    },
    getInfo: (): WalletInfo | null => {
      return this.web3Module?.getInfo() ?? null;
    },
    transaction: (txHash: string, options?: TransactionOptions) => {
      this.web3Module?.transaction(txHash, options);
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

  /** Register callback for intent predictions */
  onIntentPrediction(callback: IntentCallback): () => void {
    this.intentCallbacks.push(callback);
    return () => {
      this.intentCallbacks = this.intentCallbacks.filter((cb) => cb !== callback);
    };
  }

  /** Register callback for bot detection */
  onBotDetection(callback: BotCallback): () => void {
    this.botCallbacks.push(callback);
    return () => {
      this.botCallbacks = this.botCallbacks.filter((cb) => cb !== callback);
    };
  }

  /** Register callback for session scoring */
  onSessionScore(callback: SessionCallback): () => void {
    this.sessionScoreCallbacks.push(callback);
    return () => {
      this.sessionScoreCallbacks = this.sessionScoreCallbacks.filter((cb) => cb !== callback);
    };
  }

  /** Register a plugin */
  use(plugin: AetherPlugin): void {
    this.plugins.push(plugin);
    if (this.initialized) {
      plugin.init(this);
    }
  }

  // =========================================================================
  // PRIVATE
  // =========================================================================

  private enqueueEvent(type: string, properties: Record<string, unknown>): void {
    if (!this.eventQueue || !this.identityManager || !this.sessionManager) return;

    const session = this.sessionManager.getSession();
    const identity = this.identityManager.getIdentity();

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
        consent: this.consentModule?.getState(),
      },
    };

    this.eventQueue.enqueue(event as any);
    this.log('debug', `Event: ${type}`, properties);
  }

  private setupSPATracking(): void {
    if (typeof window === 'undefined') return;

    // History API tracking (pushState, replaceState)
    const origPush = history.pushState;
    const origReplace = history.replaceState;

    history.pushState = (...args) => {
      origPush.apply(history, args);
      setTimeout(() => this.pageView(), 0);
    };

    history.replaceState = (...args) => {
      origReplace.apply(history, args);
      setTimeout(() => this.pageView(), 0);
    };

    // Popstate (back/forward)
    window.addEventListener('popstate', () => {
      setTimeout(() => this.pageView(), 0);
    });
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
export type { AetherConfig, AetherSDKInterface } from './WebSDKTypes(CoreTypeDefinitions)';
