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
  referrerDomain: string;
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
      this.data = { referrer: '', referrerDomain: '', clickIds: {}, landingPage: '' };
      return this.data;
    }

    // SPA persistence: return stored data if already detected this session
    const STORAGE_KEY = 'aether_traffic_source';
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY);
      if (stored) {
        this.data = JSON.parse(stored);
        return this.data!;
      }
    } catch { /* sessionStorage unavailable or parse error — fall through */ }

    const params = new URLSearchParams(window.location.search);

    // Extract click IDs
    const clickIds: Record<string, string> = {};
    for (const param of CLICK_ID_PARAMS) {
      const val = params.get(param);
      if (val) clickIds[param] = val;
    }

    // Extract referrer domain (strip www. prefix)
    let referrerDomain = '';
    if (document.referrer) {
      try {
        referrerDomain = new URL(document.referrer).hostname.replace(/^www\./, '');
      } catch { /* malformed referrer URL */ }
    }

    this.data = {
      referrer: document.referrer || '',
      referrerDomain,
      utmSource: params.get('utm_source') ?? undefined,
      utmMedium: params.get('utm_medium') ?? undefined,
      utmCampaign: params.get('utm_campaign') ?? undefined,
      utmTerm: params.get('utm_term') ?? undefined,
      utmContent: params.get('utm_content') ?? undefined,
      clickIds,
      landingPage: window.location.href,
    };

    // Persist to sessionStorage so SPA navigations retain the original source
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.data)); } catch {}

    return this.data;
  }

  /** Get the detected source data for event payload */
  toEventPayload(): Record<string, unknown> {
    if (!this.data) return {};
    return { ...this.data };
  }
}
