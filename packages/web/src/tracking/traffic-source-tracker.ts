// =============================================================================
// AETHER SDK — TRAFFIC SOURCE TRACKER (Tier 2 Thin Client)
// Reads raw referrer, URL params, and click IDs. Ships to backend.
// No source classification, no channel grouping, no regex matching.
// =============================================================================

const CLICK_ID_PARAMS = [
  'gclid', 'msclkid', 'fbclid', 'ttclid', 'twclid',
  'li_fat_id', 'rdt_cid', 'scid', 'dclid', 'epik',
  'irclickid', 'aff_id',
];

export interface TrafficSourceData {
  referrer: string;
  utmSource?: string;
  utmMedium?: string;
  utmCampaign?: string;
  utmTerm?: string;
  utmContent?: string;
  clickIds: Record<string, string>;
  landingPage: string;
}

export class TrafficSourceTracker {
  private data: TrafficSourceData | null = null;

  constructor() {
    // Intentionally empty -- detect() called explicitly
  }

  /** Detect traffic source on page load and return raw data */
  detect(): TrafficSourceData {
    if (typeof window === 'undefined') {
      this.data = { referrer: '', clickIds: {}, landingPage: '' };
      return this.data;
    }

    const params = new URLSearchParams(window.location.search);

    // Extract click IDs
    const clickIds: Record<string, string> = {};
    for (const param of CLICK_ID_PARAMS) {
      const val = params.get(param);
      if (val) clickIds[param] = val;
    }

    this.data = {
      referrer: document.referrer || '',
      utmSource: params.get('utm_source') ?? undefined,
      utmMedium: params.get('utm_medium') ?? undefined,
      utmCampaign: params.get('utm_campaign') ?? undefined,
      utmTerm: params.get('utm_term') ?? undefined,
      utmContent: params.get('utm_content') ?? undefined,
      clickIds,
      landingPage: window.location.href,
    };

    return this.data;
  }

  /** Get the detected source data for event payload */
  toEventPayload(): Record<string, unknown> {
    if (!this.data) return {};
    return { ...this.data };
  }
}
