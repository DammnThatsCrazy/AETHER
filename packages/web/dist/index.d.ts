import type { AetherConfig, AetherSDKInterface, AetherPlugin, IdentityData, Identity, ResolvedIdentity, WalletInterface, ConsentInterface, CommerceInterface, AgentInterface, X402Interface, CurrentJourney, JourneyPayload } from './types';
import { EcommerceModule } from './modules/ecommerce';
import { FormAnalyticsModule } from './modules/form-analytics';
import { FeatureFlagModule } from './modules/feature-flags';
import { HeatmapModule } from './modules/heatmaps';
import { FunnelModule } from './modules/funnels';
declare class AetherSDK implements AetherSDKInterface {
    private config;
    private eventQueue;
    private sessionManager;
    private identityManager;
    private autoDiscovery;
    private consentModule;
    private web3Module;
    private semanticContext;
    private trafficTracker;
    private rewardClient;
    private ecommerceModule;
    private formAnalytics;
    private featureFlags;
    private heatmapModule;
    private funnelModule;
    private performanceModule;
    private fingerprintCollector;
    private plugins;
    private initialized;
    private debug;
    private _lastEmailHash;
    private healthAgent;
    private healthAgentConsentUnsub;
    private sdkInstanceId;
    private currentJourney;
    private journeyResumeListeners;
    private lastJourneyPauseAt;
    private journeyVisibilityHandler;
    private lastRouteCheckpointPath;
    private walletChangeListeners;
    init(config: AetherConfig): void;
    track(event: string, properties?: Record<string, unknown>): void;
    pageView(page?: string, properties?: Record<string, unknown>): void;
    conversion(event: string, value?: number, properties?: Record<string, unknown>): void;
    startJourney(nameOrType: string, properties?: JourneyPayload): CurrentJourney | null;
    pauseJourney(reason?: string, properties?: JourneyPayload): void;
    resumeJourney(reason?: string, properties?: JourneyPayload): void;
    continueJourney(stepIdOrName: string, properties?: JourneyPayload): void;
    completeJourney(reason?: string, properties?: JourneyPayload): void;
    abandonJourney(reason?: string, properties?: JourneyPayload): void;
    checkpointJourney(stepIdOrName: string, properties?: JourneyPayload): void;
    getCurrentJourney(): CurrentJourney | null;
    onJourneyResumed(callback: (identity: ResolvedIdentity) => void): () => void;
    hydrateIdentity(data: IdentityData): void;
    getIdentity(): Identity | null;
    reset(): void;
    flush(): Promise<void>;
    destroy(): void;
    wallet: WalletInterface;
    commerce: CommerceInterface;
    agent: AgentInterface;
    x402: X402Interface;
    consent: ConsentInterface;
    rewards: {
        checkEligibility: (userId: string, rewardId: string) => Promise<Record<string, unknown>>;
        getClaimPayload: (userId: string, rewardId: string) => Promise<Record<string, unknown>>;
        submitClaim: (txHash: string, rewardId: string) => Promise<Record<string, unknown>>;
    };
    ecommerce: EcommerceModule;
    featureFlag: FeatureFlagModule;
    heatmap: HeatmapModule;
    funnel: FunnelModule;
    forms: FormAnalyticsModule;
    use(plugin: AetherPlugin): void;
    /** Stable per-install SDK instance id, persisted across reloads. */
    private getSdkInstanceId;
    /**
     * Start the SDK health agent (fleet heartbeats + remote-config manifest).
     *
     * Honors privacy settings: skips entirely under DNT, and for opt-in
     * deployments (GDPR mode / opt-in cookie consent) waits until analytics
     * consent is granted before reporting any identity or metadata.
     */
    private startHealthAgent;
    /** Instantiate and start the health agent (idempotent). */
    private launchHealthAgent;
    /** Apply a remote-config manifest received from the backend to live modules. */
    private applyRemoteManifest;
    /** Fetch configuration from backend (feature flags, funnel definitions, etc.) */
    private fetchConfig;
    private initCore;
    private initWeb3;
    private initWeb2;
    private initAnalytics;
    private enqueueEvent;
    private updateJourney;
    private emitJourneyEvent;
    private setupJourneyLifecycleTracking;
    private resolveIdentity;
    private _hashEmail;
    private setupSPATracking;
    private log;
}
declare const aether: AetherSDK;
export default aether;
export { AetherSDK };
export type { AetherConfig, AetherSDKInterface, ResolvedIdentity } from './types';
