import type { ConsentState, ConsentConfig, ConsentBannerConfig, ConsentCallback } from '../types';
export declare class ConsentModule {
    private state;
    private config;
    private listeners;
    private bannerElement;
    constructor(config?: Partial<ConsentConfig>);
    /** Get current consent state */
    getState(): ConsentState;
    /** Check if a specific purpose is consented */
    hasConsent(purpose: string): boolean;
    /** Check if user has explicitly accepted or rejected (banner was acted on) */
    hasRecordedConsent(): boolean;
    /** Grant consent for specified purposes */
    grant(purposes: string[]): void;
    /** Revoke consent for specified purposes */
    revoke(purposes: string[]): void;
    /** Grant all purposes */
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
}
