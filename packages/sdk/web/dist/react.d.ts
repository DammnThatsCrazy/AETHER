import { type ReactNode } from 'react';
import type { AetherSDKInterface } from '@olympuslabs/aether-web';
import type { ConsentState } from '@olympuslabs/aether-shared/consent';
export interface AetherProviderProps {
    /**
     * SDK config. A change to `apiKey`, `siteId`, `endpoint` or `environment`
     * restarts the SDK; other options are applied once, at init.
     */
    config: Parameters<AetherSDKInterface['init']>[0];
    children: ReactNode;
}
export declare function AetherProvider({ config, children }: AetherProviderProps): import("react").JSX.Element | null;
export declare function useAether(): AetherSDKInterface;
export interface ResolvedIdentity {
    userId?: string;
    anonymousId?: string;
    traits?: Record<string, unknown>;
}
export declare function useIdentity(): ResolvedIdentity | null;
export declare function useConsentState(): ConsentState | null;
export declare function useScreenOrPageTracking(name?: string): void;
export declare function useJourneyResumed(cb: (identity: ResolvedIdentity) => void): void;
