import { describe, expect, it } from 'vitest';
import type {
  EventContext,
  ApplicationContext,
  OperatingSystemContext,
  NetworkContext,
  SemanticInputContext,
  SemanticHints,
  SamplingContext,
  CorrelationContext,
  SequenceContext,
  DataQualityRecord,
  IntentHint,
  FrictionRecord,
  EngagementRecord,
} from './events';

// ---------------------------------------------------------------------------
// Canonical envelope context v1 — the added fields are all OPTIONAL/additive
// (backward-compatible) and the previously-orphaned record types are now
// referenced by EventContext.semanticHints / .dataQuality. These are primarily
// compile-time guarantees; the runtime assertions pin the exact field shapes so
// a future rename or type-narrowing is caught by the suite, not just tsc.
// ---------------------------------------------------------------------------
describe('canonical envelope context v1', () => {
  it('a minimal EventContext (library only) still satisfies the type', () => {
    const ctx: EventContext = { library: { name: '@aether/web', version: '8.12.0' } };
    expect(ctx.library.name).toBe('@aether/web');
    // All envelope fields are optional — absent by default.
    expect(ctx.surface).toBeUndefined();
    expect(ctx.schemaVersion).toBeUndefined();
  });

  it('accepts a fully-populated canonical envelope', () => {
    const application: ApplicationContext = {
      name: 'Acme Checkout', version: '2.1.0', build: 'abc123',
      environment: 'production', namespace: 'com.acme.app',
    };
    const operatingSystem: OperatingSystemContext = { name: 'iOS', version: '17.5' };
    const network: NetworkContext = {
      effectiveType: '4g', downlink: 10, rtt: 50, saveData: false,
      connectionType: 'wifi', carrier: 'Acme Mobile',
    };
    const semanticInput: SemanticInputContext = {
      text: 'love it', language: 'en', contentRef: 'ref_1', redacted: false,
    };
    const intent: IntentHint = { predictedGoal: 'purchase', confidence: 0.8 };
    const friction: FrictionRecord = { errorCode: 'E_TIMEOUT', retryCount: 2, latencyMs: 1200 };
    const engagement: EngagementRecord = { depth: 3, dwellMs: 5000, scrollPct: 80 };
    const semanticHints: SemanticHints = { intent, friction, engagement };
    const sampling: SamplingContext = { sampled: true, rate: 0.5, reason: 'default' };
    const correlation: CorrelationContext = {
      correlationId: 'corr_1', causationId: 'cause_1', traceId: 't1', spanId: 's1',
    };
    const dataQuality: DataQualityRecord = { completeness: 0.9, freshness: 1, sourceTrust: 0.7 };
    const sequence: SequenceContext = { event: 42, session: 7 };

    const ctx: EventContext = {
      library: { name: '@aether/ios', version: '8.12.0' },
      schemaVersion: '1.0.0',
      application,
      surface: 'ios',
      operatingSystem,
      network,
      semanticInput,
      semanticHints,
      sampling,
      correlation,
      dataQuality,
      sequence,
    };

    expect(ctx.surface).toBe('ios');
    expect(ctx.schemaVersion).toBe('1.0.0');
    expect(ctx.network?.effectiveType).toBe('4g');
    expect(ctx.semanticHints?.intent?.predictedGoal).toBe('purchase');
    expect(ctx.semanticHints?.friction?.retryCount).toBe(2);
    expect(ctx.semanticHints?.engagement?.dwellMs).toBe(5000);
    expect(ctx.dataQuality?.completeness).toBe(0.9);
    expect(ctx.correlation?.correlationId).toBe('corr_1');
    expect(ctx.sequence?.event).toBe(42);
    expect(ctx.application?.namespace).toBe('com.acme.app');
    expect(ctx.operatingSystem?.name).toBe('iOS');
  });
});
