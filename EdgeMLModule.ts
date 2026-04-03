// =============================================================================
// AETHER SDK — EDGE ML MODULE
// Lightweight in-browser models for intent, bot detection, session scoring
// =============================================================================

import type { IntentVector, BotScore, BehaviorSignature, SessionScore } from './WebSDKTypes(CoreTypeDefinitions)';

/** Behavioral signal accumulator for ML features */
interface BehaviorAccumulator {
  mouseVelocities: number[];
  scrollVelocities: number[];
  hoverDurations: number[];
  timeBetweenActions: number[];
  clickPositions: Array<{ x: number; y: number; t: number }>;
  scrollDepths: number[];
  activeTime: number;
  idleTime: number;
  lastActionTime: number;
  actionCount: number;
  clickCount: number;
  scrollCount: number;
  keypressCount: number;
  pageDepth: number;
}

export interface EdgeMLCallbacks {
  onIntentPrediction: (intent: IntentVector) => void;
  onBotDetection: (score: BotScore) => void;
  onSessionScore: (score: SessionScore) => void;
}

export class EdgeMLModule {
  private callbacks: EdgeMLCallbacks;
  private behavior: BehaviorAccumulator;
  private predictionInterval: ReturnType<typeof setInterval> | null = null;
  private listeners: Array<[EventTarget, string, EventListener]> = [];
  private lastMouseX = 0;
  private lastMouseY = 0;
  private lastMouseTime = 0;

  constructor(callbacks: EdgeMLCallbacks) {
    this.callbacks = callbacks;
    this.behavior = this.createAccumulator();
  }

  /** Start collecting behavioral signals and running predictions */
  start(intervalMs = 5000): void {
    if (typeof window === 'undefined') return;

    this.attachListeners();

    // Run predictions on interval
    this.predictionInterval = setInterval(() => {
      if (this.behavior.actionCount >= 5) { // minimum data threshold
        this.runPredictions();
      }
    }, intervalMs);
  }

  /** Run all predictions manually */
  runPredictions(): void {
    const features = this.extractFeatures();

    const intent = this.predictIntent(features);
    this.callbacks.onIntentPrediction(intent);

    const botScore = this.detectBot(features);
    this.callbacks.onBotDetection(botScore);

    const sessionScore = this.scoreSession(features);
    this.callbacks.onSessionScore(sessionScore);
  }

  /** Get current behavior signature */
  getBehaviorSignature(): BehaviorSignature {
    return this.extractBehaviorSignature();
  }

  /** Destroy and clean up */
  destroy(): void {
    if (this.predictionInterval) {
      clearInterval(this.predictionInterval);
      this.predictionInterval = null;
    }
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler);
    });
    this.listeners = [];
  }

  // ===========================================================================
  // SIGNAL COLLECTION
  // ===========================================================================

  private attachListeners(): void {
    // Mouse movement → velocity tracking
    const mouseHandler = (e: Event) => {
      const me = e as MouseEvent;
      const now = Date.now();
      if (this.lastMouseTime > 0) {
        const dt = now - this.lastMouseTime;
        if (dt > 0) {
          const dx = me.clientX - this.lastMouseX;
          const dy = me.clientY - this.lastMouseY;
          const velocity = Math.sqrt(dx * dx + dy * dy) / dt;
          this.behavior.mouseVelocities.push(velocity);
          if (this.behavior.mouseVelocities.length > 100) {
            this.behavior.mouseVelocities.shift();
          }
        }
      }
      this.lastMouseX = me.clientX;
      this.lastMouseY = me.clientY;
      this.lastMouseTime = now;
      this.recordAction();
    };

    // Scroll → velocity and depth
    const scrollHandler = () => {
      const depth = window.scrollY / Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      this.behavior.scrollDepths.push(depth);
      this.behavior.scrollCount++;
      this.recordAction();
    };

    // Click positions
    const clickHandler = (e: Event) => {
      const me = e as MouseEvent;
      this.behavior.clickPositions.push({ x: me.clientX, y: me.clientY, t: Date.now() });
      if (this.behavior.clickPositions.length > 50) {
        this.behavior.clickPositions.shift();
      }
      this.behavior.clickCount++;
      this.recordAction();
    };

    // Keypress count
    const keyHandler = () => {
      this.behavior.keypressCount++;
      this.recordAction();
    };

    window.addEventListener('mousemove', mouseHandler, { passive: true });
    window.addEventListener('scroll', scrollHandler, { passive: true });
    window.addEventListener('click', clickHandler, { passive: true });
    window.addEventListener('keydown', keyHandler, { passive: true });

    this.listeners.push(
      [window, 'mousemove', mouseHandler],
      [window, 'scroll', scrollHandler],
      [window, 'click', clickHandler],
      [window, 'keydown', keyHandler]
    );
  }

  private recordAction(): void {
    const now = Date.now();
    if (this.behavior.lastActionTime > 0) {
      const gap = now - this.behavior.lastActionTime;
      this.behavior.timeBetweenActions.push(gap);
      if (this.behavior.timeBetweenActions.length > 100) {
        this.behavior.timeBetweenActions.shift();
      }
      if (gap > 5000) {
        this.behavior.idleTime += gap;
      } else {
        this.behavior.activeTime += gap;
      }
    }
    this.behavior.lastActionTime = now;
    this.behavior.actionCount++;
  }

  // ===========================================================================
  // FEATURE EXTRACTION
  // ===========================================================================

  private extractFeatures(): Record<string, number> {
    const b = this.behavior;
    const sig = this.extractBehaviorSignature();

    return {
      mouseVelocityMean: this.mean(b.mouseVelocities),
      mouseVelocityStd: this.std(b.mouseVelocities),
      timeBetweenActionsMean: sig.avgTimeBetweenActions,
      timeBetweenActionsVar: sig.actionTimingVariance,
      clickToScrollRatio: sig.clickToScrollRatio,
      mouseEntropy: sig.mouseMovementEntropy,
      navigationEntropy: sig.navigationEntropy,
      interactionDiversity: sig.interactionDiversityScore,
      activeRatio: b.activeTime / Math.max(1, b.activeTime + b.idleTime),
      actionRate: b.actionCount / Math.max(1, (Date.now() - (b.lastActionTime - b.activeTime - b.idleTime)) / 1000),
      maxScrollDepth: Math.max(0, ...b.scrollDepths),
      clickCount: b.clickCount,
      scrollCount: b.scrollCount,
      keypressCount: b.keypressCount,
      pageDepth: b.pageDepth,
      sessionDuration: (b.activeTime + b.idleTime) / 1000,
    };
  }

  private extractBehaviorSignature(): BehaviorSignature {
    const b = this.behavior;
    const totalActions = b.clickCount + b.scrollCount + b.keypressCount;

    return {
      avgTimeBetweenActions: this.mean(b.timeBetweenActions),
      actionTimingVariance: this.variance(b.timeBetweenActions),
      clickToScrollRatio: b.scrollCount > 0 ? b.clickCount / b.scrollCount : b.clickCount,
      mouseMovementEntropy: this.entropy(b.mouseVelocities.map((v) => Math.round(v * 10))),
      navigationEntropy: this.entropy(b.scrollDepths.map((d) => Math.round(d * 10))),
      interactionDiversityScore: totalActions > 0
        ? 1 - Math.max(b.clickCount, b.scrollCount, b.keypressCount) / totalActions
        : 0,
      hasNaturalPauses: b.timeBetweenActions.some((t) => t > 2000 && t < 30000),
      hasErraticMovement: this.std(b.mouseVelocities) > 2,
      hasPerfectTiming: this.variance(b.timeBetweenActions) < 100,
    };
  }

  // ===========================================================================
  // MODELS (Lightweight implementations — replaceable with TF.js)
  // ===========================================================================

  private predictIntent(features: Record<string, number>): IntentVector {
    // Simplified intent model using feature thresholds
    // In production: replace with TF.js GRU model loaded from CDN
    const exitRisk = (
      features.activeRatio < 0.3 ||
      features.maxScrollDepth < 0.1 ||
      (features.sessionDuration > 10 && features.clickCount < 2)
    );

    const conversionSignals = (
      features.maxScrollDepth > 0.7 &&
      features.clickCount > 3 &&
      features.keypressCount > 0
    );

    let predictedAction: IntentVector['predictedAction'];
    let journeyStage: IntentVector['journeyStage'];

    if (exitRisk) {
      predictedAction = 'exit';
      journeyStage = features.pageDepth > 2 ? 'consideration' : 'awareness';
    } else if (conversionSignals) {
      predictedAction = 'purchase';
      journeyStage = 'decision';
    } else if (features.activeRatio > 0.7 && features.maxScrollDepth > 0.5) {
      predictedAction = 'engage';
      journeyStage = 'consideration';
    } else if (features.sessionDuration > 60) {
      predictedAction = 'browse';
      journeyStage = 'awareness';
    } else {
      predictedAction = 'idle';
      journeyStage = 'awareness';
    }

    const confidence = Math.min(0.95, 0.3 + (features.actionRate * 0.1) + (features.maxScrollDepth * 0.3));

    return {
      predictedAction,
      confidenceScore: Math.round(confidence * 100) / 100,
      highExitRisk: exitRisk,
      highConversionProbability: conversionSignals,
      journeyStage,
      features,
      timestamp: new Date().toISOString(),
    };
  }

  private detectBot(features: Record<string, number>): BotScore {
    // Random Forest-style decision boundaries
    let botScore = 0;
    const signals = this.extractBehaviorSignature();

    // Perfect timing is a strong bot signal
    if (signals.hasPerfectTiming) botScore += 0.4;

    // Very low timing variance
    if (features.timeBetweenActionsVar < 50) botScore += 0.2;

    // No natural pauses
    if (!signals.hasNaturalPauses && features.sessionDuration > 10) botScore += 0.15;

    // Zero mouse entropy
    if (features.mouseEntropy < 0.1 && features.clickCount > 5) botScore += 0.15;

    // Very low interaction diversity
    if (signals.interactionDiversityScore < 0.05) botScore += 0.1;

    // No scroll at all with many clicks
    if (features.scrollCount === 0 && features.clickCount > 10) botScore += 0.1;

    // Human signals reduce bot score
    if (signals.hasErraticMovement) botScore -= 0.15;
    if (signals.hasNaturalPauses) botScore -= 0.1;
    if (features.keypressCount > 0) botScore -= 0.1;

    botScore = Math.max(0, Math.min(1, botScore));

    let botType: BotScore['botType'] = 'human';
    if (botScore > 0.7) {
      if (features.actionRate > 10) botType = 'scraper';
      else if (signals.hasPerfectTiming) botType = 'automated_test';
      else botType = 'click_farm';
    }

    return {
      likelyBot: botScore > 0.5,
      confidenceScore: Math.round(Math.abs(botScore - 0.5) * 2 * 100) / 100,
      botType,
      signals,
    };
  }

  private scoreSession(features: Record<string, number>): SessionScore {
    // Logistic regression-style scoring
    const engagementRaw =
      features.maxScrollDepth * 30 +
      Math.min(features.clickCount, 20) * 2 +
      Math.min(features.sessionDuration / 60, 10) * 3 +
      features.activeRatio * 20 +
      (features.keypressCount > 0 ? 10 : 0);

    const engagementScore = Math.min(100, Math.round(engagementRaw));

    // Conversion probability via sigmoid
    const conversionLogit =
      -2.5 +
      features.maxScrollDepth * 2 +
      Math.min(features.clickCount, 10) * 0.2 +
      (features.keypressCount > 0 ? 0.5 : 0) +
      features.activeRatio * 1.5;

    const conversionProbability = Math.round((1 / (1 + Math.exp(-conversionLogit))) * 100) / 100;

    let recommendedIntervention: SessionScore['recommendedIntervention'] = 'none';
    if (conversionProbability > 0.6) {
      recommendedIntervention = 'soft_cta';
    } else if (engagementScore < 20 && features.sessionDuration > 15) {
      recommendedIntervention = 'exit_offer';
    } else if (engagementScore > 50 && conversionProbability > 0.3) {
      recommendedIntervention = 'hard_cta';
    }

    return { engagementScore, conversionProbability, recommendedIntervention };
  }

  // ===========================================================================
  // MATH HELPERS
  // ===========================================================================

  private mean(arr: number[]): number {
    if (arr.length === 0) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  }

  private variance(arr: number[]): number {
    if (arr.length < 2) return 0;
    const m = this.mean(arr);
    return arr.reduce((sum, v) => sum + (v - m) ** 2, 0) / arr.length;
  }

  private std(arr: number[]): number {
    return Math.sqrt(this.variance(arr));
  }

  private entropy(arr: number[]): number {
    if (arr.length === 0) return 0;
    const counts = new Map<number, number>();
    for (const v of arr) counts.set(v, (counts.get(v) || 0) + 1);
    const total = arr.length;
    let h = 0;
    for (const count of counts.values()) {
      const p = count / total;
      if (p > 0) h -= p * Math.log2(p);
    }
    return h;
  }

  private createAccumulator(): BehaviorAccumulator {
    return {
      mouseVelocities: [],
      scrollVelocities: [],
      hoverDurations: [],
      timeBetweenActions: [],
      clickPositions: [],
      scrollDepths: [],
      activeTime: 0,
      idleTime: 0,
      lastActionTime: 0,
      actionCount: 0,
      clickCount: 0,
      scrollCount: 0,
      keypressCount: 0,
      pageDepth: 0,
    };
  }
}
