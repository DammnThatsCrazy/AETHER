// =============================================================================
// AETHER SDK — AUTOMATIC TRAFFIC SOURCE TRACKER
// Zero-config traffic source detection. No pre-created links required.
// Dynamically classifies every visit by source, medium, campaign, and channel.
// =============================================================================

import type { CampaignContext } from '../types';
import { storage, generateId, now } from '../utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TrafficType = 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'affiliate' | 'push' | 'sms' | 'display' | 'video' | 'unknown';

export interface TrafficSource {
  id: string;
  source: string;
  medium: string;
  campaign?: string;
  content?: string;
  term?: string;
  trafficType: TrafficType;
  referrerDomain?: string;
  referrerUrl?: string;
  referrerPath?: string;
  landingPage: string;
  entryTimestamp: string;
  clickIds: Record<string, string>;   // gclid, fbclid, msclkid, ttclid, etc.
  isNewUser: boolean;
}

export interface TrafficSourceConfig {
  /** Custom social domains beyond the built-in list */
  customSocialDomains?: string[];
  /** Custom search engine domains */
  customSearchDomains?: string[];
  /** Custom affiliate parameter names */
  affiliateParams?: string[];
  /** Persist attribution in localStorage (default: true) */
  persist?: boolean;
  /** Attribution window in days (default: 30) */
  attributionWindowDays?: number;
  /** Custom channel classification rules */
  channelRules?: ChannelRule[];
}

export interface ChannelRule {
  match: { source?: RegExp; medium?: RegExp; referrer?: RegExp; param?: string };
  trafficType: TrafficType;
}

// ---------------------------------------------------------------------------
// Constants — built-in source classification databases
// ---------------------------------------------------------------------------

const SEARCH_ENGINES: Record<string, string> = {
  'google': 'Google', 'bing': 'Bing', 'yahoo': 'Yahoo',
  'duckduckgo': 'DuckDuckGo', 'baidu': 'Baidu', 'yandex': 'Yandex',
  'ecosia': 'Ecosia', 'ask': 'Ask', 'aol': 'AOL', 'naver': 'Naver',
  'sogou': 'Sogou', 'qwant': 'Qwant', 'startpage': 'Startpage',
  'brave': 'Brave Search', 'perplexity': 'Perplexity',
};

const SOCIAL_PLATFORMS: Record<string, string> = {
  'facebook': 'Facebook', 'fb': 'Facebook', 'instagram': 'Instagram',
  'twitter': 'Twitter', 'x.com': 'Twitter',
  'linkedin': 'LinkedIn', 'tiktok': 'TikTok',
  'reddit': 'Reddit', 'youtube': 'YouTube', 'pinterest': 'Pinterest',
  'snapchat': 'Snapchat', 'threads': 'Threads', 'mastodon': 'Mastodon',
  'discord': 'Discord', 'telegram': 'Telegram', 'whatsapp': 'WhatsApp',
  'wechat': 'WeChat', 'weibo': 'Weibo', 'tumblr': 'Tumblr',
  'quora': 'Quora', 'medium': 'Medium', 'substack': 'Substack',
  'bluesky': 'Bluesky', 'bsky': 'Bluesky', 'twitch': 'Twitch',
  'vk': 'VK', 'line': 'LINE',
};

const EMAIL_PROVIDERS: string[] = [
  'mail.google', 'outlook', 'mail.yahoo', 'mail.aol',
  'protonmail', 'zoho', 'icloud', 'fastmail',
];

const CLICK_ID_PARAMS: Record<string, string> = {
  gclid: 'google_ads', msclkid: 'microsoft_ads', fbclid: 'facebook_ads',
  ttclid: 'tiktok_ads', twclid: 'twitter_ads', li_fat_id: 'linkedin_ads',
  rdt_cid: 'reddit_ads', scid: 'snapchat_ads', dclid: 'google_display',
  epik: 'pinterest_ads', irclickid: 'impact_affiliate', aff_id: 'affiliate',
};

const STORAGE_KEY = 'traffic_src';
const FIRST_VISIT_KEY = 'first_visit';

// ---------------------------------------------------------------------------
// Tracker
// ---------------------------------------------------------------------------

export class TrafficSourceTracker {
  private config: Required<TrafficSourceConfig>;
  private currentSource: TrafficSource | null = null;

  constructor(config: TrafficSourceConfig = {}) {
    this.config = {
      customSocialDomains: config.customSocialDomains ?? [],
      customSearchDomains: config.customSearchDomains ?? [],
      affiliateParams: config.affiliateParams ?? [],
      persist: config.persist ?? true,
      attributionWindowDays: config.attributionWindowDays ?? 30,
      channelRules: config.channelRules ?? [],
    };
  }

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  /** Detect and return the current traffic source. Runs on every page load. */
  detect(): TrafficSource {
    const params = new URLSearchParams(window.location.search);
    const referrer = document.referrer;
    const isNew = !storage.get(FIRST_VISIT_KEY);

    if (isNew) {
      storage.set(FIRST_VISIT_KEY, now());
    }

    // Priority 1: Explicit UTM parameters
    const utmSource = params.get('utm_source');
    const utmMedium = params.get('utm_medium');
    if (utmSource) {
      this.currentSource = this.buildFromUTM(params, referrer, isNew);
      this.persist();
      return this.currentSource;
    }

    // Priority 2: Ad platform click IDs (auto-tag)
    const clickIds = this.extractClickIds(params);
    if (Object.keys(clickIds).length > 0) {
      this.currentSource = this.buildFromClickId(clickIds, params, referrer, isNew);
      this.persist();
      return this.currentSource;
    }

    // Priority 3: Referrer-based classification
    if (referrer) {
      this.currentSource = this.buildFromReferrer(referrer, params, isNew);
      this.persist();
      return this.currentSource;
    }

    // Priority 4: Check for persisted attribution (within window)
    const persisted = this.loadPersisted();
    if (persisted) {
      this.currentSource = { ...persisted, landingPage: window.location.pathname, isNewUser: false };
      return this.currentSource;
    }

    // Priority 5: Direct traffic
    this.currentSource = this.buildDirect(isNew);
    this.persist();
    return this.currentSource;
  }

  /** Get the current detected source */
  getSource(): TrafficSource | null {
    return this.currentSource;
  }

  /** Serialize source for event payload */
  toEventPayload(): Record<string, unknown> {
    if (!this.currentSource) return {};
    const { id, clickIds, ...rest } = this.currentSource;
    return {
      trafficSourceId: id,
      ...rest,
      clickIds: Object.keys(clickIds).length > 0 ? clickIds : undefined,
    };
  }

  // =========================================================================
  // BUILDERS
  // =========================================================================

  private buildFromUTM(params: URLSearchParams, referrer: string, isNew: boolean): TrafficSource {
    const source = params.get('utm_source')!;
    const medium = params.get('utm_medium') ?? 'unknown';
    const trafficType = this.classifyByMedium(medium, source, referrer);

    return {
      id: this.generateSourceId(source, medium, params.get('utm_campaign')),
      source,
      medium,
      campaign: params.get('utm_campaign') ?? undefined,
      content: params.get('utm_content') ?? undefined,
      term: params.get('utm_term') ?? undefined,
      trafficType,
      referrerDomain: this.extractDomain(referrer),
      referrerUrl: referrer || undefined,
      referrerPath: this.extractPath(referrer),
      landingPage: window.location.pathname,
      entryTimestamp: now(),
      clickIds: this.extractClickIds(params),
      isNewUser: isNew,
    };
  }

  private buildFromClickId(
    clickIds: Record<string, string>,
    params: URLSearchParams,
    referrer: string,
    isNew: boolean,
  ): TrafficSource {
    // Determine source from click ID type
    const firstKey = Object.keys(clickIds)[0];
    const adPlatform = CLICK_ID_PARAMS[firstKey] ?? 'paid';
    const source = adPlatform.replace('_ads', '').replace('_affiliate', '');

    return {
      id: this.generateSourceId(source, 'cpc', params.get('utm_campaign')),
      source,
      medium: 'cpc',
      campaign: params.get('utm_campaign') ?? undefined,
      content: params.get('utm_content') ?? undefined,
      term: params.get('utm_term') ?? undefined,
      trafficType: adPlatform.includes('affiliate') ? 'affiliate' : 'paid',
      referrerDomain: this.extractDomain(referrer),
      referrerUrl: referrer || undefined,
      referrerPath: this.extractPath(referrer),
      landingPage: window.location.pathname,
      entryTimestamp: now(),
      clickIds,
      isNewUser: isNew,
    };
  }

  private buildFromReferrer(referrer: string, params: URLSearchParams, isNew: boolean): TrafficSource {
    const domain = this.extractDomain(referrer) ?? '';

    // Check custom channel rules first
    for (const rule of this.config.channelRules) {
      if (rule.match.referrer?.test(domain)) {
        return {
          id: this.generateSourceId(domain, rule.trafficType),
          source: domain,
          medium: rule.trafficType,
          trafficType: rule.trafficType,
          referrerDomain: domain,
          referrerUrl: referrer,
          referrerPath: this.extractPath(referrer),
          landingPage: window.location.pathname,
          entryTimestamp: now(),
          clickIds: {},
          isNewUser: isNew,
        };
      }
    }

    // Search engines
    const searchEngine = this.matchDomain(domain, SEARCH_ENGINES, this.config.customSearchDomains);
    if (searchEngine) {
      return {
        id: this.generateSourceId(searchEngine, 'organic'),
        source: searchEngine,
        medium: 'organic',
        term: params.get('q') ?? params.get('query') ?? params.get('search_query') ?? undefined,
        trafficType: 'organic',
        referrerDomain: domain,
        referrerUrl: referrer,
        referrerPath: this.extractPath(referrer),
        landingPage: window.location.pathname,
        entryTimestamp: now(),
        clickIds: {},
        isNewUser: isNew,
      };
    }

    // Social platforms
    const socialPlatform = this.matchDomain(domain, SOCIAL_PLATFORMS, this.config.customSocialDomains);
    if (socialPlatform) {
      return {
        id: this.generateSourceId(socialPlatform, 'social'),
        source: socialPlatform,
        medium: 'social',
        trafficType: 'social',
        referrerDomain: domain,
        referrerUrl: referrer,
        referrerPath: this.extractPath(referrer),
        landingPage: window.location.pathname,
        entryTimestamp: now(),
        clickIds: {},
        isNewUser: isNew,
      };
    }

    // Email providers
    const isEmail = EMAIL_PROVIDERS.some((ep) => domain.includes(ep));
    if (isEmail) {
      return {
        id: this.generateSourceId(domain, 'email'),
        source: domain,
        medium: 'email',
        trafficType: 'email',
        referrerDomain: domain,
        referrerUrl: referrer,
        referrerPath: this.extractPath(referrer),
        landingPage: window.location.pathname,
        entryTimestamp: now(),
        clickIds: {},
        isNewUser: isNew,
      };
    }

    // Generic referral
    return {
      id: this.generateSourceId(domain, 'referral'),
      source: domain,
      medium: 'referral',
      trafficType: 'referral',
      referrerDomain: domain,
      referrerUrl: referrer,
      referrerPath: this.extractPath(referrer),
      landingPage: window.location.pathname,
      entryTimestamp: now(),
      clickIds: {},
      isNewUser: isNew,
    };
  }

  private buildDirect(isNew: boolean): TrafficSource {
    return {
      id: this.generateSourceId('direct', 'none'),
      source: 'direct',
      medium: 'none',
      trafficType: 'direct',
      landingPage: window.location.pathname,
      entryTimestamp: now(),
      clickIds: {},
      isNewUser: isNew,
    };
  }

  // =========================================================================
  // CLASSIFICATION
  // =========================================================================

  private classifyByMedium(medium: string, source: string, referrer: string): TrafficType {
    const m = medium.toLowerCase();
    const s = source.toLowerCase();

    // Check custom rules first
    for (const rule of this.config.channelRules) {
      if (rule.match.medium?.test(m) || rule.match.source?.test(s)) {
        return rule.trafficType;
      }
    }

    if (['cpc', 'ppc', 'paid', 'paidsearch', 'paid_search', 'search_ad'].includes(m)) return 'paid';
    if (['display', 'banner', 'cpm', 'programmatic'].includes(m)) return 'display';
    if (['social', 'social-media', 'social_media', 'sm'].includes(m)) return 'social';
    if (['email', 'newsletter', 'drip', 'nurture'].includes(m)) return 'email';
    if (['affiliate', 'partner', 'referral_partner'].includes(m)) return 'affiliate';
    if (['push', 'push_notification', 'webpush'].includes(m)) return 'push';
    if (['sms', 'text', 'mms'].includes(m)) return 'sms';
    if (['video', 'youtube', 'preroll'].includes(m)) return 'video';
    if (['organic', 'seo'].includes(m)) return 'organic';
    if (['referral', 'link'].includes(m)) return 'referral';

    return 'unknown';
  }

  // =========================================================================
  // HELPERS
  // =========================================================================

  private matchDomain(domain: string, builtIn: Record<string, string>, custom: string[] = []): string | null {
    for (const [key, name] of Object.entries(builtIn)) {
      if (domain.includes(key)) return name;
    }
    for (const d of custom) {
      if (domain.includes(d)) return d;
    }
    return null;
  }

  private extractClickIds(params: URLSearchParams): Record<string, string> {
    const ids: Record<string, string> = {};
    const allParams = [...Object.keys(CLICK_ID_PARAMS), ...this.config.affiliateParams];
    for (const param of allParams) {
      const val = params.get(param);
      if (val) ids[param] = val;
    }
    return ids;
  }

  private extractDomain(url: string): string | undefined {
    if (!url) return undefined;
    try { return new URL(url).hostname; } catch { return undefined; }
  }

  private extractPath(url: string): string | undefined {
    if (!url) return undefined;
    try { return new URL(url).pathname; } catch { return undefined; }
  }

  private generateSourceId(source: string, medium: string, campaign?: string | null): string {
    const parts = [source, medium, campaign ?? ''].filter(Boolean).join('::').toLowerCase();
    // Simple deterministic hash for deduplication
    let hash = 0;
    for (let i = 0; i < parts.length; i++) {
      hash = ((hash << 5) - hash + parts.charCodeAt(i)) | 0;
    }
    return `src_${Math.abs(hash).toString(36)}`;
  }

  private persist(): void {
    if (!this.config.persist || !this.currentSource) return;
    storage.set(STORAGE_KEY, {
      ...this.currentSource,
      _expiresAt: Date.now() + this.config.attributionWindowDays * 86_400_000,
    });
  }

  private loadPersisted(): TrafficSource | null {
    if (!this.config.persist) return null;
    const stored = storage.get<TrafficSource & { _expiresAt: number }>(STORAGE_KEY);
    if (!stored || (stored._expiresAt && stored._expiresAt < Date.now())) {
      storage.remove(STORAGE_KEY);
      return null;
    }
    return stored;
  }
}
