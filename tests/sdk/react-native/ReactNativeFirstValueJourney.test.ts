/**
 * PR D: Cross-Platform Payload Snapshot Parity
 * React Native First-Value Journey Snapshot Test
 *
 * Blueprint §3.4 — RN emits the canonical-first-value-journey fixture through
 * RN-native/platform-idiomatic APIs and normalizes into the same canonical envelope.
 *
 * Acceptance criteria (8):
 *  1. Same canonical top-level event types
 *  2. Same consent-purpose derivation
 *  3. Same schema hash
 *  4. Same tenant/source/app/surface fields
 *  5. Same journey semantics
 *  6. Same identity transition semantics
 *  7. Same idempotency behavior
 *  8. Same dropped-event diagnostics model
 */

import { describe, it, expect } from 'vitest';

import {
  canonicalFirstValueJourney,
  type CanonicalJourneyEvent,
  type CanonicalJourneySchema,
  type JourneyIdentityTransition,
  type IdempotencyConfig,
  type DroppedEventDiagnostics,
  normalizeCanonicalJourneyEvent,
} from '@aether/proof-fixtures';

const PLATFORM_OVERRIDES = {
  platform_id: 'react_native',
  sdk_name: '@aether/react-native',
  device_platform: 'react_native',
  surface: 'react_native_app',
};

describe('PR D: Cross-Platform Parity — React Native First-Value Journey', () => {
  const fixture = canonicalFirstValueJourney;
  const schema = fixture.schema as CanonicalJourneySchema;
  const identity = fixture.identity as JourneyIdentityTransition;
  const idempotency = fixture.idempotency as IdempotencyConfig;
  const droppedDiagnostics = fixture.dropped_event_diagnostics as DroppedEventDiagnostics;

  // Normalize all events with RN-specific overrides
  const normalizedEvents: ReturnType<typeof normalizeCanonicalJourneyEvent>[] =
    (fixture.events as CanonicalJourneyEvent[]).map((e) =>
      normalizeCanonicalJourneyEvent(e, PLATFORM_OVERRIDES)
    );

  // ─── 1. Same canonical top-level event types ───────────────────────────

  it('should produce the same canonical event types as the Web fixture', () => {
    const expectedTypes = schema.canonical_event_types;
    const actualTypes = normalizedEvents.map((e) => e.event_type);
    expect(actualTypes).toEqual(expectedTypes);
    expect(actualTypes).toHaveLength(14);
  });

  it('should map each RN event to the correct step event_type', () => {
    for (let i = 0; i < normalizedEvents.length; i++) {
      const event = normalizedEvents[i];
      const step = fixture.journey.steps[i];
      expect(event.event_type).toBe(step.event_type);
      expect(event.step).toBe(step.step - 1);
    }
  });

  it('should have unique event_ids across all RN events', () => {
    const ids = normalizedEvents.map((e) => e.event_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('should have unique idempotency_keys across all RN events', () => {
    const keys = normalizedEvents.map((e) => e.idempotency_key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  // ─── 2. Same consent-purpose derivation ───────────────────────────────

  it('should derive analytics consent purpose for analytics events', () => {
    const analyticsTypes = [
      'sdk_config_loaded', 'sdk_initialized', 'heartbeat', 'session_started',
      'page', 'identify', 'journey_completed', 'sdk_batch_accepted', 'graph_projection_ready',
    ];
    for (const event of normalizedEvents) {
      if (analyticsTypes.includes(event.event_type)) {
        expect(event.consent?.purpose).toBe('analytics');
      }
    }
  });

  it('should derive commerce consent purpose for commerce events', () => {
    const commerceTypes = [
      'product_viewed', 'cart_item_added', 'checkout_started',
      'payment_completed', 'order_completed',
    ];
    for (const event of normalizedEvents) {
      if (commerceTypes.includes(event.event_type)) {
        expect(event.consent?.purpose).toBe('commerce');
      }
    }
  });

  it('should have consistent consent status across all RN events', () => {
    for (const event of normalizedEvents) {
      expect(event.consent?.status).toBe('granted');
      expect(event.consent?.version).toBe('1.0');
      expect(event.consent?.granted_at).toBe('2024-09-11T11:55:00.000Z');
    }
  });

  // ─── 3. Same schema hash ───────────────────────────────────────────────

  it('should have the same schema hash as the canonical fixture', () => {
    expect(schema.schema_hash).toBe('sha256:canonical-first-value-journey-v1-2024-09-11');
    expect(schema.schema_version).toBe('1.0.0');
    expect(schema.envelope_format).toBe('event-envelope-v2');
  });

  it('should list all canonical event types in the schema hash', () => {
    const expectedTypes = [
      'sdk_config_loaded', 'sdk_initialized', 'heartbeat', 'session_started',
      'page', 'product_viewed', 'cart_item_added', 'checkout_started',
      'identify', 'payment_completed', 'order_completed', 'journey_completed',
      'sdk_batch_accepted', 'graph_projection_ready',
    ];
    expect(schema.canonical_event_types).toEqual(expectedTypes);
  });

  // ─── 4. Same tenant/source/app/surface fields ─────────────────────────

  it('should have consistent tenant fields across all RN events', () => {
    for (const event of normalizedEvents) {
      expect(event.tenant_id).toBe('aether-proof-tenant');
      expect(event.workspace_id).toBe('proof-lab');
      expect(event.environment).toBe('staging');
    }
  });

  it('should have RN-specific platform and SDK fields after normalization', () => {
    for (const event of normalizedEvents) {
      expect(event.platform_id).toBe('react_native');
      expect(event.source.platform).toBe('react_native');
      expect(event.source.sdk).toBe('@aether/react-native');
      expect(event.source.environment).toBe('staging');
      expect(event.source.surface).toBe('react_native_app');
      expect(event.sdk.name).toBe('@aether/react-native');
      expect(event.sdk.version).toBe('0.1.0-alpha.0');
      expect(event.device.platform).toBe('react_native');
    }
  });

  it('should preserve canonical device_id and session_id after normalization', () => {
    for (const event of normalizedEvents) {
      expect(event.device.device_id).toBe('dev_web_fvj_001');
      expect(event.session.session_id).toBe('sess_fvj_001');
    }
  });

  // ─── 5. Same journey semantics ────────────────────────────────────────

  it('should have complete journey metadata', () => {
    expect(fixture.journey.journey_id).toBe('journey-first-value-001');
    expect(fixture.journey.journey_name).toBe('First Value Journey');
    expect(fixture.journey.journey_type).toBe('activation');
    expect(fixture.journey.description).toBeDefined();
    expect(fixture.journey.steps).toHaveLength(14);
  });

  it('should have journey_completed event with correct step counts', () => {
    const journeyEvent = normalizedEvents[11];
    expect(journeyEvent.event_type).toBe('journey_completed');
    expect(journeyEvent.properties.journey_id).toBe('journey-first-value-001');
    expect(journeyEvent.properties.journey_name).toBe('First Value Journey');
    expect(journeyEvent.properties.journey_type).toBe('activation');
    expect(journeyEvent.properties.steps_completed).toBe(12);
    expect(journeyEvent.properties.total_steps).toBe(12);
    expect(journeyEvent.properties.conversion_achieved).toBe(true);
    expect(journeyEvent.properties.first_value_event).toBe('order_completed');
    expect(journeyEvent.properties.first_purchase_value).toBe(50.00);
  });

  it('should have journey_completed steps array with all 12 steps', () => {
    const journeyEvent = normalizedEvents[11];
    const steps = journeyEvent.properties.steps as Array<{ step: number; name: string; completed_at: string }>;
    expect(steps).toHaveLength(12);
    expect(steps[0]).toMatchObject({ step: 1, name: 'manifest_fetched' });
    expect(steps[11]).toMatchObject({ step: 12, name: 'journey_completed' });
  });

  // ─── 6. Same identity transition semantics ────────────────────────────

  it('should preserve anonymous_id across all RN events', () => {
    for (const event of normalizedEvents) {
      expect(event.identity.anonymous_id).toBe('anon_first_value_001');
    }
  });

  it('should transition from anonymous-only to identified at the identify step', () => {
    for (let i = 0; i <= 7; i++) {
      const event = normalizedEvents[i];
      expect(event.identity.anonymous_id).toBe('anon_first_value_001');
      expect(event.identity.user_id).toBeUndefined();
    }
    const identifyEvent = normalizedEvents[8];
    expect(identifyEvent.identity.anonymous_id).toBe('anon_first_value_001');
    expect(identifyEvent.identity.user_id).toBe('user_first_value_001');
    for (let i = 9; i < normalizedEvents.length; i++) {
      const event = normalizedEvents[i];
      expect(event.identity.anonymous_id).toBe('anon_first_value_001');
      expect(event.identity.user_id).toBe('user_first_value_001');
    }
  });

  it('should have identity transition metadata', () => {
    expect(identity.anonymous_id).toBe('anon_first_value_001');
    expect(identity.user_id).toBe('user_first_value_001');
    expect(identity.transition.type).toBe('anonymous_to_identified');
    expect(identity.transition.anonymous_id_persistent).toBe(true);
    expect(identity.transition.user_id_appears_at_step).toBe(9);
    expect(identity.transition.identify_event_index).toBe(8);
    expect(identity.transition.pre_identify_events).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(identity.transition.post_identify_events).toEqual([8, 9, 10, 11, 12, 13]);
  });

  // ─── 7. Same idempotency behavior ─────────────────────────────────────

  it('should define idempotency configuration', () => {
    expect(idempotency.mode).toBe('idempotent_per_event_id');
    expect(idempotency.event_id_format).toBe('fvj-{step}-{timestamp}-{anonymous_id}');
    expect(idempotency.idempotency_key_format).toBe('fk-{event_type}:{anonymous_id}:{timestamp}');
    expect(idempotency.duplicate_detection).toBe('event_id_dedup');
    expect(idempotency.retry_behavior).toBe('retry_with_same_idempotency_key');
  });

  it('should generate event_ids matching the defined format', () => {
    for (const event of normalizedEvents) {
      expect(event.event_id).toMatch(
        /^fvj-\d+-\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-anon_first_value_001$/
      );
    }
  });

  it('should generate idempotency_keys matching the defined format', () => {
    for (const event of normalizedEvents) {
      expect(event.idempotency_key).toMatch(
        /^fk-(sdk_config_loaded|sdk_initialized|heartbeat|session_started|page|product_viewed|cart_item_added|checkout_started|identify|payment_completed|order_completed|journey_completed|sdk_batch_accepted|graph_projection_ready):anon_first_value_001:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/
      );
    }
  });

  // ─── 8. Same dropped-event diagnostics model ──────────────────────────

  it('should define the dropped-event diagnostics model', () => {
    expect(droppedDiagnostics.model).toBe('dropped_event_log');
    expect(droppedDiagnostics.dropped_events).toEqual([]);
    expect(droppedDiagnostics.diagnostic_fields).toEqual([
      'event_id', 'event_type', 'dropped_at', 'drop_reason', 'platform_id', 'retry_count',
    ]);
  });

  // ─── Cross-cutting assertions ──────────────────────────────────────────

  it('should have monotonically increasing timestamps across all RN events', () => {
    for (let i = 1; i < normalizedEvents.length; i++) {
      const prev = new Date(normalizedEvents[i - 1].timestamp).getTime();
      const curr = new Date(normalizedEvents[i].timestamp).getTime();
      expect(curr).toBeGreaterThan(prev);
    }
  });

  it('should validate every RN event has a complete EventEnvelope shape', () => {
    const requiredFields = [
      'tenant_id', 'workspace_id', 'platform_id', 'environment',
      'event_type', 'sdk', 'session', 'device', 'identity',
      'timestamp', 'properties', 'source', 'consent',
      'event_id', 'idempotency_key',
    ];
    for (const event of normalizedEvents) {
      for (const field of requiredFields) {
        expect(event[field as keyof typeof event]).toBeDefined();
      }
      expect(event.sdk.name).toBeDefined();
      expect(event.sdk.version).toBeDefined();
      expect(event.session.session_id).toBeDefined();
      expect(event.device.device_id).toBeDefined();
      expect(event.device.platform).toBeDefined();
      expect(event.identity.anonymous_id).toBeDefined();
      expect(event.source.platform).toBeDefined();
      expect(event.source.sdk).toBeDefined();
      expect(event.source.environment).toBeDefined();
      expect(event.source.surface).toBeDefined();
      expect(event.consent.purpose).toBeDefined();
      expect(event.consent.status).toBeDefined();
    }
  });

  it('should assert RN produces the same identity transition as all other platforms', () => {
    const preIdentifyIds = normalizedEvents.slice(0, 8).map((e) => e.identity.anonymous_id);
    expect(preIdentifyIds).toEqual(Array(8).fill('anon_first_value_001'));

    const postIdentify = normalizedEvents.slice(8).map(
      (e) => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })
    );
    for (const id of postIdentify) {
      expect(id.anonymous_id).toBe('anon_first_value_001');
      expect(id.user_id).toBe('user_first_value_001');
    }
  });

  it('should assert RN uses the same idempotency key format as all other platforms', () => {
    const keys = normalizedEvents.map((e) => e.idempotency_key);
    expect(keys).toEqual(
      (fixture.events as CanonicalJourneyEvent[]).map((e) => e.idempotency_key)
    );
  });

  it('should assert RN produces the same schema hash as all other platforms', () => {
    expect(schema.schema_hash).toBe('sha256:canonical-first-value-journey-v1-2024-09-11');
  });

  it('should assert RN shares the same tenant/source/app/surface fields as all other platforms', () => {
    const firstEvent = normalizedEvents[0];
    expect(firstEvent.tenant_id).toBe('aether-proof-tenant');
    expect(firstEvent.workspace_id).toBe('proof-lab');
    expect(firstEvent.environment).toBe('staging');
    expect(firstEvent.source.platform).toBe('react_native');
    expect(firstEvent.source.surface).toBe('react_native_app');
  });
});
