       // =============================================================================
       // Aether SDK — Shared Consent Contract (v8.12.0)
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
* - financial_activity: Read-only derivatives trading analytics: account connections, orders, fills, positions, collateral, margin, funding, fees, PnL, risk profiling, agent trading activity, campaign linkage, and governed model training. Always requires explicit opt-in.
* - credit: Credit signals, account observations, and credit decisions. Always requires explicit opt-in. Always requires explicit opt-in.
* - location: Precise or coarse location observations and geofence transitions. Always requires explicit opt-in. Always requires explicit opt-in.
* - economic_observability: Read-only stablecoin economic intelligence: canonical asset and deployment identity, transfer/payment/mint/burn/bridge/swap observations, valuation and peg monitoring, support assertions, finality, flow aggregates, and reconciliation. Always requires explicit opt-in.
* - cross_chain_observability: Read-only interoperability intelligence: cross-network message lifecycle, paths, gateways, applications, intents, asset legs, security policy snapshots, verification and delivery actors, and reconciliation. Aether never relays or routes. Always requires explicit opt-in.
* - fraud_prevention: Bot detection, fraud and abuse signal analysis, and platform security monitoring. Always requires explicit opt-in. Always requires explicit opt-in.
        */
       export type ConsentPurpose =
         | 'analytics'
 | 'marketing'
 | 'personalization'
 | 'web3'
 | 'agent'
 | 'commerce'
 | 'financial_activity'
 | 'credit'
 | 'location'
 | 'economic_observability'
 | 'cross_chain_observability'
 | 'fraud_prevention';

       export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
         'analytics',
 'marketing',
 'personalization',
 'web3',
 'agent',
 'commerce',
 'financial_activity',
 'credit',
 'location',
 'economic_observability',
 'cross_chain_observability',
 'fraud_prevention',
       ] as const;

       /** Purposes that ALWAYS require explicit opt-in (never granted by accept-all). */
       export const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = [
         'financial_activity',
 'credit',
 'location',
 'economic_observability',
 'cross_chain_observability',
 'fraud_prevention',
       ] as const;

       /** Consent state stored locally by each SDK and stamped onto every event. */
       export interface ConsentState {
         analytics: boolean;
 marketing: boolean;
 personalization: boolean;
 web3: boolean;
 agent: boolean;
 commerce: boolean;
 financial_activity: boolean;
 credit: boolean;
 location: boolean;
 economic_observability: boolean;
 cross_chain_observability: boolean;
 fraud_prevention: boolean;
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
 financial_activity: false,
 credit: false,
 location: false,
 economic_observability: false,
 cross_chain_observability: false,
 fraud_prevention: false,
       };
