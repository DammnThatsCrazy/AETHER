       // =============================================================================
       // Aether SDK — Shared Consent Contract (v8.10.0)
       // DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json
       // Run: python scripts/generate_contracts.py
       // =============================================================================

       /**
        * Canonical consent purposes. Web SDK, native SDKs, and the backend validator
        * MUST all recognize these exact strings.
        *
        * - analytics: Basic product usage and operational analytics. Required for core platform function.
* - marketing: Attribution, experiments, conversion tracking, and advertising attribution.
* - personalization: Cross-device fingerprinting, recommendations, and personalised content. Required for device fingerprint generation.
* - web3: Wallet connections, on-chain transactions, and decentralised protocol observations.
* - agent: Agentic workflow observations, AI task lifecycle, delegation, and tool usage.
* - commerce: Payments, approvals, entitlements, subscriptions, orders, and access control events.
* - credit: Credit signals, account observations, and credit decisions. Always requires explicit opt-in. Always requires explicit opt-in.
* - location: Precise or coarse location observations and geofence transitions. Always requires explicit opt-in. Always requires explicit opt-in.
        */
       export type ConsentPurpose =
         | 'analytics'
 | 'marketing'
 | 'personalization'
 | 'web3'
 | 'agent'
 | 'commerce'
 | 'credit'
 | 'location';

       export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
         'analytics',
 'marketing',
 'personalization',
 'web3',
 'agent',
 'commerce',
 'credit',
 'location',
       ] as const;

       /** Purposes that ALWAYS require explicit opt-in (never granted by accept-all). */
       export const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = [
         'credit',
 'location',
       ] as const;

       /** Consent state stored locally by each SDK and stamped onto every event. */
       export interface ConsentState {
         analytics: boolean;
 marketing: boolean;
 personalization: boolean;
 web3: boolean;
 agent: boolean;
 commerce: boolean;
 credit: boolean;
 location: boolean;
         updatedAt: string;
         policyVersion: string;
       }

       export interface ConsentConfig {
         purposes: ConsentPurpose[];
         policyUrl: string;
         policyVersion: string;
       }

       /**
        * Default consent state used by every SDK at init (no consent granted).
        * Consent UI pre-checks purposes based on defaultEnabled in the registry.
        */
       export const DEFAULT_CONSENT_STATE: Omit<ConsentState, 'updatedAt' | 'policyVersion'> = {
         analytics: true,
 marketing: false,
 personalization: false,
 web3: false,
 agent: false,
 commerce: false,
 credit: false,
 location: false,
       };
