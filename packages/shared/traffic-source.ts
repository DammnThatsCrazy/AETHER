// =============================================================================
// Aether SDK — Canonical Traffic-Source Contract (v1.0.0)
// DO NOT EDIT — generated from packages/shared/contracts/traffic-source-registry.json
// Run: python scripts/generate_contracts.py
//
// SDKs observe acquisition evidence; the backend classifies. These types exist
// so SDKs and product surfaces can name backend classifications without ever
// computing them locally. Classification and campaign identity are separate
// dimensions: none of these values implies a campaign.
// =============================================================================

export const TRAFFIC_SOURCE_CONTRACT_VERSION = '1.0.0';

/** Where the visit physically came from, independent of who paid for it. */
export type TrafficOrigin =
  | 'external'
  | 'internal'
  | 'app_store'
  | 'offline'
  | 'unknown';

/** Whether money is known to be behind the touch. */
export type EconomicClass =
  | 'paid'
  | 'unpaid'
  | 'unknown'
  | 'nonhuman';

/** Coarse channel grouping used for reporting rollups. */
export type ChannelFamily =
  | 'search'
  | 'social'
  | 'email'
  | 'referral'
  | 'affiliate'
  | 'partner'
  | 'ai'
  | 'agent'
  | 'push'
  | 'sms'
  | 'app_store'
  | 'internal'
  | 'direct'
  | 'machine'
  | 'unknown';

/** Canonical source classification. 'direct_unknown' is the honest fallback —
 * it never claims the user typed a URL. */
export type SourceClass =
  | 'paid_search'
  | 'paid_social'
  | 'display'
  | 'organic_search'
  | 'organic_social'
  | 'owned_referral'
  | 'external_referral'
  | 'email'
  | 'affiliate'
  | 'partner'
  | 'ai_referral'
  | 'agent_referral'
  | 'push'
  | 'sms'
  | 'app_store_referral'
  | 'internal_navigation'
  | 'direct_unknown'
  | 'machine_referral'
  | 'unknown';

/** How the entry evidence was physically observed. */
export type EntryMethod =
  | 'verified_source_link'
  | 'server_redirect'
  | 'web_referrer'
  | 'paid_click_id'
  | 'utm_declaration'
  | 'android_install_referrer'
  | 'android_app_link'
  | 'ios_universal_link'
  | 'ios_custom_url'
  | 'ios_adattributionkit'
  | 'push_notification'
  | 'email_link'
  | 'qr_code'
  | 'nfc'
  | 'vanity_url'
  | 'internal_navigation'
  | 'manual_sdk_evidence'
  | 'unknown';

/** Strength of the evidence behind the classification. */
export type ProofLevel =
  | 'cryptographic'
  | 'platform_verified'
  | 'domain_verified'
  | 'server_observed'
  | 'declared'
  | 'inferred'
  | 'none';

export const TRAFFIC_ORIGINS: readonly TrafficOrigin[] = [
  'external',
  'internal',
  'app_store',
  'offline',
  'unknown',
] as const;

export const ECONOMIC_CLASSES: readonly EconomicClass[] = [
  'paid',
  'unpaid',
  'unknown',
  'nonhuman',
] as const;

export const CHANNEL_FAMILIES: readonly ChannelFamily[] = [
  'search',
  'social',
  'email',
  'referral',
  'affiliate',
  'partner',
  'ai',
  'agent',
  'push',
  'sms',
  'app_store',
  'internal',
  'direct',
  'machine',
  'unknown',
] as const;

export const SOURCE_CLASSES: readonly SourceClass[] = [
  'paid_search',
  'paid_social',
  'display',
  'organic_search',
  'organic_social',
  'owned_referral',
  'external_referral',
  'email',
  'affiliate',
  'partner',
  'ai_referral',
  'agent_referral',
  'push',
  'sms',
  'app_store_referral',
  'internal_navigation',
  'direct_unknown',
  'machine_referral',
  'unknown',
] as const;

export const ENTRY_METHODS: readonly EntryMethod[] = [
  'verified_source_link',
  'server_redirect',
  'web_referrer',
  'paid_click_id',
  'utm_declaration',
  'android_install_referrer',
  'android_app_link',
  'ios_universal_link',
  'ios_custom_url',
  'ios_adattributionkit',
  'push_notification',
  'email_link',
  'qr_code',
  'nfc',
  'vanity_url',
  'internal_navigation',
  'manual_sdk_evidence',
  'unknown',
] as const;

export const PROOF_LEVELS: readonly ProofLevel[] = [
  'cryptographic',
  'platform_verified',
  'domain_verified',
  'server_observed',
  'declared',
  'inferred',
  'none',
] as const;

export interface SourceClassDefaults {
  channelFamily: ChannelFamily;
  economicClass: EconomicClass;
  /** Customer-facing label. 'direct_unknown' renders as 'Direct / Unknown',
   * never as a typed-URL claim. */
  label: string;
}

export const SOURCE_CLASS_DEFAULTS: Readonly<Record<SourceClass, SourceClassDefaults>> = {
  "paid_search": { channelFamily: "search", economicClass: "paid", label: "Paid Search" },
  "paid_social": { channelFamily: "social", economicClass: "paid", label: "Paid Social" },
  "display": { channelFamily: "search", economicClass: "paid", label: "Display" },
  "organic_search": { channelFamily: "search", economicClass: "unpaid", label: "Organic Search" },
  "organic_social": { channelFamily: "social", economicClass: "unpaid", label: "Organic Social" },
  "owned_referral": { channelFamily: "referral", economicClass: "unpaid", label: "Verified Source" },
  "external_referral": { channelFamily: "referral", economicClass: "unknown", label: "Referral" },
  "email": { channelFamily: "email", economicClass: "unpaid", label: "Email" },
  "affiliate": { channelFamily: "affiliate", economicClass: "paid", label: "Affiliate" },
  "partner": { channelFamily: "partner", economicClass: "unknown", label: "Partner" },
  "ai_referral": { channelFamily: "ai", economicClass: "unpaid", label: "AI Referral" },
  "agent_referral": { channelFamily: "agent", economicClass: "unpaid", label: "Agent Referral" },
  "push": { channelFamily: "push", economicClass: "unpaid", label: "Push" },
  "sms": { channelFamily: "sms", economicClass: "unpaid", label: "SMS" },
  "app_store_referral": { channelFamily: "app_store", economicClass: "unknown", label: "App Install" },
  "internal_navigation": { channelFamily: "internal", economicClass: "unpaid", label: "Internal Navigation" },
  "direct_unknown": { channelFamily: "direct", economicClass: "unknown", label: "Direct / Unknown" },
  "machine_referral": { channelFamily: "machine", economicClass: "nonhuman", label: "Machine Referral" },
  "unknown": { channelFamily: "unknown", economicClass: "unknown", label: "Unknown" },
};

/** Historical source_class values normalized at API boundaries. */
export const LEGACY_SOURCE_CLASS_ALIASES: Readonly<Record<string, SourceClass>> =
  {"direct": "direct_unknown"};

/** Normalize a possibly-legacy source_class value to the canonical vocabulary. */
export function canonicalSourceClass(value: string): SourceClass | string {
  return LEGACY_SOURCE_CLASS_ALIASES[value] ?? value;
}
