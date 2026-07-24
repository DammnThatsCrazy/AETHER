// =============================================================================
// Aether SDK — Acquisition Evidence Contract
//
// The canonical, platform-agnostic structure that captures raw campaign and
// referral evidence from the SDK at the landing moment.
//
// Resolution priority (server-side CampaignResolver):
//   1. canonicalCampaignId — explicit Aether UUID, validated against tenant
//   2. platform + externalAccountId + externalCampaignId — exact external ref
//   3. utmId — authoritative alias lookup (confidence 0.99)
//   4. platform + externalAccountId + utmSource + utmMedium + utmCampaign — composite alias (0.95)
//   5. tenant-unique utmCampaign alias (0.85)
//   6. unresolved → Mapping Review queue
//
// Invariant: canonicalCampaignId, if supplied, is ALWAYS validated server-side
// against tenant ownership before use. Never trust it blindly.
// referralToken is likewise opaque client-side and is never a campaign or
// provider assertion until a server verifies and interprets it.
// =============================================================================

export interface AcquisitionEvidence {
  // UTM parameters (URL-decoded, raw values preserved as captured)
  utmSource?: string;
  utmMedium?: string;
  /** utm_campaign — the campaign identifier token, NOT the human display name. */
  utmCampaign?: string;
  utmContent?: string;
  utmTerm?: string;
  /** utm_id — when present, highest-confidence UTM alias (0.99). */
  utmId?: string;

  // Platform identity — supply when available from the ad platform SDK or
  // URL parameters (e.g. ttclid → platform=tiktok_ads).
  platform?: string;
  externalAccountId?: string;
  externalCampaignId?: string;

  /**
   * Explicit Aether campaign UUID. Only supply when Aether itself embedded this
   * token (e.g. via a tracking template). Always validated server-side against
   * tenant ownership — a forged UUID is rejected, not trusted.
   */
  canonicalCampaignId?: string;

  // Click IDs — preserved as evidence for audit; NOT used for auto-resolution.
  clickIds?: {
    gclid?: string;
    fbclid?: string;
    msclkid?: string;
    ttclid?: string;
    liEFatId?: string;
    rdtCid?: string;
    [key: string]: string | undefined;
  };

  // Landing context
  referrer?: string;
  referrerDomain?: string;
  landingPage?: string;

  /**
   * Opaque referral token captured from the `aether_ref` landing parameter.
   * The SDK does not parse or trust this value; verification and interpretation
   * are server-owned.
   */
  referralToken?: string;

  /**
   * How the entry evidence was physically observed (canonical EntryMethod from
   * the traffic-source registry, e.g. 'web_referrer', 'android_install_referrer',
   * 'ios_universal_link'). Descriptive observation only — the backend classifier
   * remains the sole owner of the final classification.
   */
  entryMethod?: string;

  /**
   * Host of the destination the user arrived at (deep link / app link /
   * universal link host). This is where the user LANDED, never who referred
   * them — it must not be reported as referrerDomain.
   */
  destinationDomain?: string;
  /** One-way hash of the destination path when path privacy is configured. */
  destinationPathHash?: string;

  /** True when this evidence is the persisted first touch (vs latest touch). */
  firstTouch?: boolean;

  // Temporal metadata
  firstCapturedAt?: string;  // ISO 8601
  lastObservedAt?: string;   // ISO 8601
  /** When the underlying evidence expires and stops attaching to new events. */
  evidenceExpiresAt?: string;  // ISO 8601

  // Disambiguation
  sessionId?: string;

  // Schema version for forward-compatibility
  schemaVersion: number;

  // Backward-compatibility shims (deprecated — one release window)
  /** @deprecated use utmCampaign */
  name?: string;
  /** @deprecated use externalCampaignId */
  campaignId?: string;
}

/** Minimal evidence used when only UTM params are available. */
export type UtmOnlyEvidence = Pick<AcquisitionEvidence,
  'utmSource' | 'utmMedium' | 'utmCampaign' | 'utmId' | 'schemaVersion'
>;

/** Evidence from a paid-media click (platform + external IDs present). */
export type PaidMediaEvidence = AcquisitionEvidence & {
  platform: string;
  externalAccountId: string;
  externalCampaignId: string;
};

export const ACQUISITION_EVIDENCE_SCHEMA_VERSION = 3;

/** Build a minimal AcquisitionEvidence from URL search params (browser). */
export function evidenceFromSearchParams(params: URLSearchParams): AcquisitionEvidence {
  const clickIds: AcquisitionEvidence['clickIds'] = {};
  const knownClickIds = ['gclid', 'fbclid', 'msclkid', 'ttclid', 'liEFatId', 'rdtCid'];
  for (const key of knownClickIds) {
    const val = params.get(key);
    if (val) clickIds[key] = val;
  }

  return {
    utmSource: params.get('utm_source') ?? undefined,
    utmMedium: params.get('utm_medium') ?? undefined,
    utmCampaign: params.get('utm_campaign') ?? undefined,
    utmContent: params.get('utm_content') ?? undefined,
    utmTerm: params.get('utm_term') ?? undefined,
    utmId: params.get('utm_id') ?? undefined,
    canonicalCampaignId: params.get('aether_cid') ?? undefined,
    referralToken: params.get('aether_ref') ?? undefined,
    clickIds: Object.keys(clickIds).length > 0 ? clickIds : undefined,
    landingPage: (globalThis as any).window?.location?.href,
    referrer: (globalThis as any).document?.referrer || undefined,
    firstCapturedAt: new Date().toISOString(),
    schemaVersion: ACQUISITION_EVIDENCE_SCHEMA_VERSION,
  };
}
