// =============================================================================
// AETHER SDK — React Native Tiered Semantic Context
// Cross-platform context enrichment bridging to native collectors.
// Tier 1: Essential → Tier 2: Functional → Tier 3: Rich
// =============================================================================

import { Platform, AppState, AppStateStatus } from 'react-native';

// ---------------------------------------------------------------------------
// Types (shared with Web SDK)
// ---------------------------------------------------------------------------

export type ContextTier = 1 | 2 | 3;

export interface Tier1Context {
  eventId: string;
  timestamp: string;
  sdkVersion: string;
  platform: 'react-native';
  device: {
    type: string;
    os: string;
    language: string;
    online: boolean;
  };
}

export interface Tier2Context {
  journeyStage: 'new' | 'returning' | 'engaged' | 'converting' | 'retained';
  screenPath: string[];
  sessionDuration: number;
  appState: string;
  screenDepth: number;
  eventSequenceIndex: number;
  entryPoint: string;
}

export interface Tier3Context {
  inferredIntent: { action: string; confidence: number; journeyPhase: string } | null;
  sentimentSignals: {
    frustration: number;
    engagement: number;
    urgency: number;
    confusion: number;
  };
  errorLog: {
    errorCount: number;
    lastError: { message: string; type: string; timestamp: string } | null;
    errorRate: number;
  };
}

export interface SemanticContextEnvelope {
  tier: ContextTier;
  t1: Tier1Context;
  t2?: Tier2Context;
  t3?: Tier3Context;
}

// ---------------------------------------------------------------------------
// Collector
// ---------------------------------------------------------------------------

const SDK_VERSION = '5.0.0';

class RNSemanticContextCollector {
  // Tier 2 state
  private screenPath: string[] = [];
  private eventSequence = 0;
  private sessionStartMs = Date.now();
  private entryPoint = '';
  private screenDepth = 0;
  private currentAppState: AppStateStatus = AppState.currentState;

  // Tier 3 state
  private errorBuffer: { message: string; type: string; timestamp: string }[] = [];
  private backtrackCount = 0;
  private interactionCount = 0;

  // Consent
  private analyticsConsent = false;
  private marketingConsent = false;

  private appStateSubscription: any = null;

  constructor() {
    this.appStateSubscription = AppState.addEventListener('change', (state) => {
      this.currentAppState = state;
    });
  }

  // =========================================================================
  // PUBLIC API
  // =========================================================================

  collect(): SemanticContextEnvelope {
    this.eventSequence++;
    const tier = this.resolveTier();

    const envelope: SemanticContextEnvelope = {
      tier,
      t1: this.collectTier1(),
    };

    if (tier >= 2) envelope.t2 = this.collectTier2();
    if (tier >= 3) envelope.t3 = this.collectTier3();

    return envelope;
  }

  recordScreen(name: string): void {
    if (this.screenPath.length >= 2 && this.screenPath[this.screenPath.length - 2] === name) {
      this.backtrackCount++;
    }
    this.screenPath.push(name);
    if (this.screenPath.length > 50) {
      this.screenPath = this.screenPath.slice(-50);
    }
    this.screenDepth++;
    if (!this.entryPoint) this.entryPoint = name;
  }

  recordError(message: string, type: string): void {
    this.errorBuffer.push({ message, type, timestamp: new Date().toISOString() });
    if (this.errorBuffer.length > 100) this.errorBuffer.shift();
  }

  recordInteraction(): void { this.interactionCount++; }

  updateConsent(analytics: boolean, marketing: boolean): void {
    this.analyticsConsent = analytics;
    this.marketingConsent = marketing;
  }

  resetSession(): void {
    this.screenPath = [];
    this.eventSequence = 0;
    this.sessionStartMs = Date.now();
    this.entryPoint = '';
    this.screenDepth = 0;
    this.backtrackCount = 0;
    this.interactionCount = 0;
    this.errorBuffer = [];
  }

  destroy(): void {
    this.appStateSubscription?.remove();
  }

  // =========================================================================
  // TIER COLLECTORS
  // =========================================================================

  private collectTier1(): Tier1Context {
    return {
      eventId: this.generateId(),
      timestamp: new Date().toISOString(),
      sdkVersion: SDK_VERSION,
      platform: 'react-native',
      device: {
        type: Platform.isPad ? 'tablet' : 'mobile',
        os: `${Platform.OS} ${Platform.Version}`,
        language: 'en', // Would use RNLocalize in production
        online: true,
      },
    };
  }

  private collectTier2(): Tier2Context {
    const elapsed = Date.now() - this.sessionStartMs;
    return {
      journeyStage: this.inferJourneyStage(elapsed),
      screenPath: this.screenPath.slice(-20),
      sessionDuration: elapsed,
      appState: this.currentAppState,
      screenDepth: this.screenDepth,
      eventSequenceIndex: this.eventSequence,
      entryPoint: this.entryPoint || this.screenPath[0] || 'unknown',
    };
  }

  private collectTier3(): Tier3Context {
    const windowMs = 300_000;
    const cutoff = Date.now() - windowMs;
    const recentErrors = this.errorBuffer.filter((e) => new Date(e.timestamp).getTime() >= cutoff);
    const errorRate = recentErrors.length / (windowMs / 60_000);

    const elapsedS = (Date.now() - this.sessionStartMs) / 1000;
    const engagement = Math.min(1, (this.screenDepth / 10) * 0.4 + Math.min(elapsedS / 120, 1) * 0.6);
    const frustration = Math.min(1, (recentErrors.length * 0.2) / 5);
    const confusion = Math.min(1, (this.backtrackCount * 0.4) / 3);
    const urgency = this.eventSequence > 0
      ? Math.min(1, (this.screenDepth / this.eventSequence) * 2)
      : 0;

    return {
      inferredIntent: null,
      sentimentSignals: {
        frustration: +frustration.toFixed(3),
        engagement: +engagement.toFixed(3),
        urgency: +urgency.toFixed(3),
        confusion: +confusion.toFixed(3),
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

  private resolveTier(): ContextTier {
    if (this.analyticsConsent && this.marketingConsent) return 3;
    if (this.analyticsConsent) return 2;
    return 1;
  }

  private inferJourneyStage(elapsedMs: number): Tier2Context['journeyStage'] {
    if (elapsedMs < 10_000 && this.screenDepth <= 1) return 'new';
    if (this.screenDepth > 5 || elapsedMs > 180_000) return 'engaged';
    return 'returning';
  }

  private generateId(): string {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
}

export const semanticContext = new RNSemanticContextCollector();
export { RNSemanticContextCollector };
