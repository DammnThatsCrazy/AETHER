// =============================================================================
// AETHER SDK — TIERED SEMANTIC CONTEXT
// Enriches every event with layered context based on consent + configuration.
// Tier 1: Essential (always) → Tier 2: Functional → Tier 3: Rich
// =============================================================================

import type { ConsentState, DeviceContext, IntentVector, SessionScore } from '../types';
import { generateId, now, getDeviceContext } from '../utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ContextTier = 1 | 2 | 3;

/** Tier 1 — Essential (always collected, anonymized) */
export interface Tier1Context {
  eventId: string;
  timestamp: string;
  sdkVersion: string;
  platform: 'web' | 'ios' | 'android' | 'react-native';
  device: {
    type: DeviceContext['type'];
    os: string;
    language: string;
    online: boolean;
  };
}

/** Tier 2 — Functional (requires analytics consent) */
export interface Tier2Context {
  journeyStage: 'new' | 'returning' | 'engaged' | 'converting' | 'retained';
  screenPath: string[];
  sessionDuration: number;
  appState: 'active' | 'background' | 'inactive';
  pageDepth: number;
  eventSequenceIndex: number;
  entryPoint: string;
  referrerCategory: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
}

/** Tier 3 — Rich (requires full consent) */
export interface Tier3Context {
  inferredIntent: {
    action: string;
    confidence: number;
    journeyPhase: string;
  } | null;
  sentimentSignals: {
    frustration: number;      // 0-1 rage clicks, error encounters
    engagement: number;       // 0-1 time on page, scroll depth
    urgency: number;          // 0-1 navigation speed, direct paths
    confusion: number;        // 0-1 backtracking, repeated searches
  };
  interactionHeatmap: {
    clickZones: { x: number; y: number; count: number }[];
    scrollReach: number;      // 0-100 percentage
    hoverDwellMs: number;     // average hover dwell time
    activeTimeMs: number;     // time with actual interaction
    idleTimeMs: number;       // time with no interaction
  };
  errorLog: {
    errorCount: number;
    lastError: { message: string; type: string; timestamp: string } | null;
    errorRate: number;        // errors per minute
  };
}

/** Combined semantic context envelope */
export interface SemanticContext {
  tier: ContextTier;
  t1: Tier1Context;
  t2?: Tier2Context;
  t3?: Tier3Context;
}

// ---------------------------------------------------------------------------
// Collector Configuration
// ---------------------------------------------------------------------------

export interface SemanticContextConfig {
  maxTier?: ContextTier;
  heatmapResolution?: number;     // grid size for click zone bucketing
  screenPathMaxLength?: number;   // max entries in screen path history
  sentimentWindowMs?: number;     // time window for sentiment calculation
}

const DEFAULTS: Required<SemanticContextConfig> = {
  maxTier: 3,
  heatmapResolution: 10,
  screenPathMaxLength: 50,
  sentimentWindowMs: 300_000,     // 5 minutes
};

// ---------------------------------------------------------------------------
// Semantic Context Collector
// ---------------------------------------------------------------------------

export class SemanticContextCollector {
  private config: Required<SemanticContextConfig>;
  private sdkVersion: string;

  // Tier 2 state
  private screenPath: string[] = [];
  private eventSequence = 0;
  private sessionStartMs = Date.now();
  private entryPoint = '';
  private referrerCategory: Tier2Context['referrerCategory'] = 'unknown';
  private sessionPageViews = 0;

  // Tier 3 state
  private clickBuffer: { x: number; y: number; ts: number }[] = [];
  private scrollReach = 0;
  private hoverDwellSamples: number[] = [];
  private lastActivityTs = Date.now();
  private activeTimeMs = 0;
  private idleTimeMs = 0;
  private rageClickCount = 0;
  private backtrackCount = 0;
  private searchCount = 0;
  private errorBuffer: { message: string; type: string; timestamp: string }[] = [];

  // External signal injection
  private lastIntent: Tier3Context['inferredIntent'] = null;
  private lastSessionScore: SessionScore | null = null;

  // Listeners
  private listeners: (() => void)[] = [];

  constructor(sdkVersion: string, config: SemanticContextConfig = {}) {
    this.sdkVersion = sdkVersion;
    this.config = { ...DEFAULTS, ...config };
    if (typeof window !== 'undefined') {
      this.entryPoint = window.location.pathname;
      this.detectReferrerCategory();
      this.attachDOMListeners();
    }
  }

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  /** Build semantic context for an event at the resolved tier */
  collect(consent: ConsentState | null): SemanticContext {
    const resolvedTier = this.resolveTier(consent);
    this.eventSequence++;

    const ctx: SemanticContext = {
      tier: resolvedTier,
      t1: this.collectTier1(),
    };

    if (resolvedTier >= 2) ctx.t2 = this.collectTier2();
    if (resolvedTier >= 3) ctx.t3 = this.collectTier3();

    return ctx;
  }

  /** Record a screen/page navigation */
  recordScreen(path: string): void {
    const prev = this.screenPath[this.screenPath.length - 1];
    if (prev && this.screenPath.length >= 2 && this.screenPath[this.screenPath.length - 2] === path) {
      this.backtrackCount++;
    }
    this.screenPath.push(path);
    if (this.screenPath.length > this.config.screenPathMaxLength) {
      this.screenPath = this.screenPath.slice(-this.config.screenPathMaxLength);
    }
    this.sessionPageViews++;
  }

  /** Inject intent prediction from EdgeML */
  setIntent(intent: IntentVector): void {
    this.lastIntent = {
      action: intent.predictedAction,
      confidence: intent.confidenceScore,
      journeyPhase: intent.journeyStage,
    };
  }

  /** Inject session score from EdgeML */
  setSessionScore(score: SessionScore): void {
    this.lastSessionScore = score;
  }

  /** Record an error for tier 3 error log */
  recordError(message: string, type: string): void {
    this.errorBuffer.push({ message, type, timestamp: now() });
    if (this.errorBuffer.length > 100) this.errorBuffer.shift();
  }

  /** Record a search event for sentiment tracking */
  recordSearch(): void {
    this.searchCount++;
  }

  /** Clean up DOM listeners */
  destroy(): void {
    this.listeners.forEach((unsub) => unsub());
    this.listeners = [];
  }

  // =========================================================================
  // TIER COLLECTORS
  // =========================================================================

  private collectTier1(): Tier1Context {
    const device = typeof window !== 'undefined' ? getDeviceContext() : null;
    return {
      eventId: generateId(),
      timestamp: now(),
      sdkVersion: this.sdkVersion,
      platform: 'web',
      device: {
        type: device?.type ?? 'desktop',
        os: device?.os ?? 'unknown',
        language: device?.language ?? 'en',
        online: device?.online ?? true,
      },
    };
  }

  private collectTier2(): Tier2Context {
    const elapsed = Date.now() - this.sessionStartMs;
    return {
      journeyStage: this.inferJourneyStage(),
      screenPath: [...this.screenPath],
      sessionDuration: elapsed,
      appState: typeof document !== 'undefined'
        ? (document.visibilityState === 'visible' ? 'active' : 'background')
        : 'active',
      pageDepth: this.sessionPageViews,
      eventSequenceIndex: this.eventSequence,
      entryPoint: this.entryPoint,
      referrerCategory: this.referrerCategory,
    };
  }

  private collectTier3(): Tier3Context {
    const nowMs = Date.now();
    const windowStart = nowMs - this.config.sentimentWindowMs;

    // Build click zone heatmap
    const recentClicks = this.clickBuffer.filter((c) => c.ts >= windowStart);
    const grid = this.config.heatmapResolution;
    const zoneMap = new Map<string, { x: number; y: number; count: number }>();
    for (const click of recentClicks) {
      const gx = Math.floor((click.x / window.innerWidth) * grid);
      const gy = Math.floor((click.y / window.innerHeight) * grid);
      const key = `${gx},${gy}`;
      const existing = zoneMap.get(key);
      if (existing) existing.count++;
      else zoneMap.set(key, { x: gx, y: gy, count: 1 });
    }

    // Compute sentiment signals
    const windowMinutes = this.config.sentimentWindowMs / 60_000;
    const recentErrors = this.errorBuffer.filter((e) => new Date(e.timestamp).getTime() >= windowStart);
    const errorRate = recentErrors.length / Math.max(windowMinutes, 0.1);

    const frustration = Math.min(1, (this.rageClickCount * 0.3 + recentErrors.length * 0.2) / 5);
    const engagement = Math.min(1, this.scrollReach / 100 * 0.4 + Math.min(this.activeTimeMs / 120_000, 1) * 0.6);
    const urgency = Math.min(1, this.eventSequence > 0 ? (this.sessionPageViews / this.eventSequence) * 2 : 0);
    const confusion = Math.min(1, (this.backtrackCount * 0.4 + Math.min(this.searchCount, 5) * 0.1) / 3);

    const avgHoverDwell = this.hoverDwellSamples.length > 0
      ? this.hoverDwellSamples.reduce((a, b) => a + b, 0) / this.hoverDwellSamples.length
      : 0;

    return {
      inferredIntent: this.lastIntent,
      sentimentSignals: {
        frustration: +frustration.toFixed(3),
        engagement: +engagement.toFixed(3),
        urgency: +urgency.toFixed(3),
        confusion: +confusion.toFixed(3),
      },
      interactionHeatmap: {
        clickZones: Array.from(zoneMap.values()),
        scrollReach: this.scrollReach,
        hoverDwellMs: Math.round(avgHoverDwell),
        activeTimeMs: this.activeTimeMs,
        idleTimeMs: this.idleTimeMs,
      },
      errorLog: {
        errorCount: this.errorBuffer.length,
        lastError: this.errorBuffer.length > 0 ? this.errorBuffer[this.errorBuffer.length - 1] : null,
        errorRate: +errorRate.toFixed(2),
      },
    };
  }

  // =========================================================================
  // HELPERS
  // =========================================================================

  private resolveTier(consent: ConsentState | null): ContextTier {
    const max = this.config.maxTier;
    if (!consent) return Math.min(max, 1) as ContextTier;
    if (consent.analytics && consent.marketing) return Math.min(max, 3) as ContextTier;
    if (consent.analytics) return Math.min(max, 2) as ContextTier;
    return 1;
  }

  private inferJourneyStage(): Tier2Context['journeyStage'] {
    if (this.lastSessionScore) {
      if (this.lastSessionScore.conversionProbability > 0.7) return 'converting';
      if (this.lastSessionScore.engagementScore > 0.6) return 'engaged';
    }
    const duration = Date.now() - this.sessionStartMs;
    if (duration < 10_000 && this.sessionPageViews <= 1) return 'new';
    if (this.sessionPageViews > 5 || duration > 180_000) return 'engaged';
    return 'returning';
  }

  private detectReferrerCategory(): void {
    if (typeof document === 'undefined' || !document.referrer) {
      this.referrerCategory = 'direct';
      return;
    }
    try {
      const ref = new URL(document.referrer).hostname.toLowerCase();
      const params = new URLSearchParams(window.location.search);

      const searchEngines = ['google', 'bing', 'yahoo', 'duckduckgo', 'baidu', 'yandex'];
      const socialNetworks = ['facebook', 'twitter', 'linkedin', 'instagram', 'tiktok', 'reddit', 'youtube', 'pinterest', 'snapchat', 'threads'];

      if (params.get('gclid') || params.get('msclkid') || params.get('fbclid')) {
        this.referrerCategory = 'paid';
      } else if (searchEngines.some((se) => ref.includes(se))) {
        this.referrerCategory = 'organic';
      } else if (socialNetworks.some((sn) => ref.includes(sn))) {
        this.referrerCategory = 'social';
      } else if (params.get('utm_medium')?.toLowerCase() === 'email') {
        this.referrerCategory = 'email';
      } else {
        this.referrerCategory = 'referral';
      }
    } catch {
      this.referrerCategory = 'unknown';
    }
  }

  private attachDOMListeners(): void {
    if (typeof window === 'undefined') return;

    // Click tracking (tier 3 heatmap + rage click detection)
    let lastClickTs = 0;
    let rapidClickCount = 0;
    const onClick = (e: MouseEvent) => {
      const ts = Date.now();
      this.clickBuffer.push({ x: e.clientX, y: e.clientY, ts });
      if (this.clickBuffer.length > 500) this.clickBuffer = this.clickBuffer.slice(-500);

      // Rage click detection: 3+ clicks within 1s
      if (ts - lastClickTs < 1000) {
        rapidClickCount++;
        if (rapidClickCount >= 3) this.rageClickCount++;
      } else {
        rapidClickCount = 1;
      }
      lastClickTs = ts;
    };
    window.addEventListener('click', onClick, { passive: true, capture: true });
    this.listeners.push(() => window.removeEventListener('click', onClick, true));

    // Scroll tracking (tier 3 scroll reach)
    const onScroll = () => {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const docHeight = Math.max(
        document.documentElement.scrollHeight - document.documentElement.clientHeight,
        1,
      );
      const pct = Math.round((scrollTop / docHeight) * 100);
      if (pct > this.scrollReach) this.scrollReach = pct;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    this.listeners.push(() => window.removeEventListener('scroll', onScroll));

    // Active/idle tracking (tier 3)
    const IDLE_THRESHOLD = 30_000;
    let activityTimer: ReturnType<typeof setInterval>;
    const trackActivity = () => {
      const nowMs = Date.now();
      const delta = nowMs - this.lastActivityTs;
      if (delta > IDLE_THRESHOLD) {
        this.idleTimeMs += delta;
      } else {
        this.activeTimeMs += delta;
      }
      this.lastActivityTs = nowMs;
    };
    const onActivity = () => { this.lastActivityTs = Date.now(); };
    activityTimer = setInterval(trackActivity, 5000);
    window.addEventListener('mousemove', onActivity, { passive: true });
    window.addEventListener('keydown', onActivity, { passive: true });
    window.addEventListener('touchstart', onActivity, { passive: true });
    this.listeners.push(() => {
      clearInterval(activityTimer);
      window.removeEventListener('mousemove', onActivity);
      window.removeEventListener('keydown', onActivity);
      window.removeEventListener('touchstart', onActivity);
    });
  }
}
