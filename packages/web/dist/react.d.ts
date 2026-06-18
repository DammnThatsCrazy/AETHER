import { type ReactNode } from 'react';
import type { AetherSDK } from './index';
import type { ConsentState } from '@aether/shared/consent';
export interface AetherProviderProps {
    config: Parameters<AetherSDK['init']>[0];
    children: ReactNode;
}
export declare function AetherProvider({ config, children }: AetherProviderProps): import("react").JSX.Element;
export declare function useAether(): AetherSDK;
export interface ResolvedIdentity {
    userId?: string;
    anonymousId?: string;
    traits?: Record<string, unknown>;
}
export declare function useIdentity(): ResolvedIdentity | null;
export declare function useConsentState(): ConsentState | null;
export declare function useScreenOrPageTracking(name?: string): void;
export declare function useJourneyResumed(cb: (identity: ResolvedIdentity) => void): void;
