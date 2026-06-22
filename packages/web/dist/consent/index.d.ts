import type { ConsentState, ConsentConfig, ConsentPurpose, ConsentBannerConfig, ConsentCallback } from '../types';
export declare class ConsentModule {
    private state;
    private config;
    private listeners;
    private bannerElement;
    constructor(config?: Partial<ConsentConfig>);
    /** Get current consent state */
    getState(): ConsentState;
    /** Check if a specific purpose is consented */
    hasConsent(purpose: ConsentPurpose): boolean;
    /** Check if user has explicitly accepted or rejected (banner was acted on) */
    hasRecordedConsent(): boolean;
    /** Grant consent for specified purposes */
    grant(purposes: ConsentPurpose[]): void;
    /** Revoke consent for specified purposes. Revoking personalization deletes cached fingerprint. */
    revoke(purposes: ConsentPurpose[]): void;
    /**
     * Grant all purposes that do NOT require explicit opt-in (credit and location are excluded).
     * To grant credit or location, call grant(['credit']) or grant(['location']) explicitly.
     */
    grantAll(): void;
    /** Revoke all purposes */
    revokeAll(): void;
    /** Register a listener for consent changes */
    onUpdate(callback: ConsentCallback): () => void;
    /** Show the consent banner */
    showBanner(config?: ConsentBannerConfig): void;
    /** Hide the consent banner */
    hideBanner(): void;
    /** Destroy the consent module */
    destroy(): void;
    private loadConsent;
    private persist;
    private notify;
    private clearFingerprintCache;
}
