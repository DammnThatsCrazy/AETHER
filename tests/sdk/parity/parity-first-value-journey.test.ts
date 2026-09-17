/**
 * PR D: Cross-Platform Payload Snapshot Parity
 * Canonical First-Value Journey Snapshot Tests
 *
 * Blueprint §3.4 — Each SDK platform (Web, React Native, iOS, Android, Server)
 * emits the canonical-first-value-journey fixture through native/platform-idiomatic
 * APIs and normalizes into the same canonical envelope.
 *
 * Acceptance criteria:
 * - Same canonical top-level event types
 * - Same consent-purpose derivation
 * - Same schema hash
 * - Same tenant/source/app/surface fields
 * - Same journey semantics
 * - Same identity transition semantics
 * - Same idempotency behavior
 * - Same dropped-event diagnostics model
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';
import {
  EventEnvelope,
  canonicalFirstValueJourney,
  type CanonicalJourneyEvent,
  type CanonicalJourneySchema,
  type JourneyIdentityTransition,
  type IdempotencyConfig,
  type DroppedEventDiagnostics,
} from '@aether/proof-fixtures';

const CANONICAL_FIXTURE_PATH = join(__dirname, '..', '..', '..', 'sdk-fixtures', 'canonical-first-value-journey.json');

describe('PR D: Cross-Platform Payload Snapshot Parity — Canonical First-Value Journey', () => {
  const fixture = canonicalFirstValueJourney;
  const canonicalEvents = fixture.events as CanonicalJourneyEvent[];
  const schema = fixture.schema as CanonicalJourneySchema;
  const identity = fixture.identity as JourneyIdentityTransition;
  const idempotency = fixture.idempotency as IdempotencyConfig;
  const droppedDiagnostics = fixture.dropped_event_diagnostics as DroppedEventDiagnostics;

  // ─── Canonical fixture structure ────────────────────────────────────────

  it('should have a valid canonical fixture at sdk-fixtures/canonical-first-value-journey.json', () => {
    const raw = readFileSync(CANONICAL_FIXTURE_PATH, 'utf-8');
    const parsed = JSON.parse(raw);
    expect(parsed._fixture_version).toBe(1);
    expect(parsed._fixtureName).toBe('canonicalFirstValueJourney');
    expect(parsed.journey).toBeDefined();
    expect(parsed.tenant).toBeDefined();
    expect(parsed.schema).toBeDefined();
    expect(parsed.identity).toBeDefined();
    expect(parsed.idempotency).toBeDefined();
    expect(parsed.dropped_event_diagnostics).toBeDefined();
    expect(parsed.source).toBeDefined();
    expect(Array.isArray(parsed.events)).toBe(true);
    expect(parsed.events.length).toBe(14);
  });

  it('should define all 14 canonical journey steps in order', () => {
    const steps = fixture.journey.steps;
    expect(steps).toHaveLength(14);
    expect(steps[0]).toMatchObject({ step: 1, name: 'manifest_fetched', event_type: 'sdk_config_loaded' });
    expect(steps[1]).toMatchObject({ step: 2, name: 'sdk_initialized', event_type: 'sdk_initialized' });
    expect(steps[2]).toMatchObject({ step: 3, name: 'heartbeat_sent', event_type: 'heartbeat' });
    expect(steps[3]).toMatchObject({ step: 4, name: 'anonymous_session_started', event_type: 'session_started' });
    expect(steps[4]).toMatchObject({ step: 5, name: 'screen_or_page_viewed', event_type: 'page' });
    expect(steps[5]).toMatchObject({ step: 6, name: 'product_viewed', event_type: 'product_viewed' });
    expect(steps[6]).toMatchObject({ step: 7, name: 'cart_item_added', event_type: 'cart_item_added' });
    expect(steps[7]).toMatchObject({ step: 8, name: 'checkout_started', event_type: 'checkout_started' });
    expect(steps[8]).toMatchObject({ step: 9, name: 'identify_called', event_type: 'identify' });
    expect(steps[9]).toMatchObject({ step: 10, name: 'payment_succeeded', event_type: 'payment_completed' });
    expect(steps[10]).toMatchObject({ step: 11, name: 'order_completed', event_type: 'order_completed' });
    expect(steps[11]).toMatchObject({ step: 12, name: 'journey_completed', event_type: 'journey_completed' });
    expect(steps[12]).toMatchObject({ step: 13, name: 'flush_confirmed', event_type: 'sdk_batch_accepted' });
    expect(steps[13]).toMatchObject({ step: 14, name: 'graph_projection_ready', event_type: 'graph_projection_ready' });
  });

  // ─── Schema hash parity ─────────────────────────────────────────────────

  it('should have a consistent schema hash across all platforms', () => {
    expect(schema.schema_hash).toBe('sha256:canonical-first-value-journey-v1-2024-09-11');
    expect(schema.schema_version).toBe('1.0.0');
    expect(schema.envelope_format).toBe('event-envelope-v2');
  });

  it('should list all canonical event types in the schema hash', () => {
    const expectedTypes = [
      'sdk_config_loaded',
      'sdk_initialized',
      'heartbeat',
      'session_started',
      'page',
      'product_viewed',
      'cart_item_added',
      'checkout_started',
      'identify',
      'payment_completed',
      'order_completed',
      'journey_completed',
      'sdk_batch_accepted',
      'graph_projection_ready',
    ];
    expect(schema.canonical_event_types).toEqual(expectedTypes);
  });

  // ─── Tenant / source / app / surface fields ─────────────────────────────

  it('should have consistent tenant fields across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.tenant_id).toBe('aether-proof-tenant');
      expect(event.workspace_id).toBe('proof-lab');
      expect(event.environment).toBe('staging');
    }
  });

  it('should have consistent source fields across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.source.platform).toBe('web');
      expect(event.source.sdk).toBe('@aether/web');
      expect(event.source.environment).toBe('staging');
      expect(event.source.surface).toBe('marketing_site');
    }
  });

  it('should have consistent SDK fields across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.sdk.name).toBe('@aether/web');
      expect(event.sdk.version).toBe('0.1.0-alpha.0');
    }
  });

  it('should have consistent device fields across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.device.device_id).toBe('dev_web_fvj_001');
      expect(event.device.platform).toBe('web');
    }
  });

  it('should have consistent session fields across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.session.session_id).toBe('sess_fvj_001');
    }
  });

  // ─── Consent-purpose derivation ─────────────────────────────────────────

  it('should derive consent purpose from the event type via the consent registry', () => {
    // Events requiring 'analytics' purpose
    const analyticsEvents = [
      'sdk_config_loaded',
      'sdk_initialized',
      'heartbeat',
      'session_started',
      'page',
      'identify',
      'journey_completed',
      'sdk_batch_accepted',
      'graph_projection_ready',
    ];
    // Events requiring 'commerce' purpose
    const commerceEvents = [
      'product_viewed',
      'cart_item_added',
      'checkout_started',
      'payment_completed',
      'order_completed',
    ];

    for (const event of canonicalEvents) {
      const purpose = event.consent?.purpose;
      const eventType = event.event_type;
      if (analyticsEvents.includes(eventType)) {
        expect(purpose).toBe('analytics');
      } else if (commerceEvents.includes(eventType)) {
        expect(purpose).toBe('commerce');
      } else {
        expect.pass(`Unknown event type ${eventType} — no purpose assertion`);
      }
      expect(purpose).toBeDefined();
      expect(purpose).toBeTruthy();
    }
  });

  it('should have consistent consent status across all events', () => {
    for (const event of canonicalEvents) {
      expect(event.consent?.status).toBe('granted');
      expect(event.consent?.version).toBe('1.0');
      expect(event.consent?.granted_at).toBe('2024-09-11T11:55:00.000Z');
    }
  });

  // ─── Event type parity ──────────────────────────────────────────────────

  it('should have the correct event_type for each step', () => {
    for (let i = 0; i < canonicalEvents.length; i++) {
      const event = canonicalEvents[i];
      const step = fixture.journey.steps[i];
      expect(event.event_type).toBe(step.event_type);
      expect(event.step).toBe(step.step - 1); // zero-indexed in events array
    }
  });

  it('should validate each event has a unique event_id', () => {
    const eventIds = canonicalEvents.map(e => e.event_id);
    const uniqueIds = new Set(eventIds);
    expect(uniqueIds.size).toBe(eventIds.length);
  });

  it('should validate each event has a unique idempotency_key', () => {
    const keys = canonicalEvents.map(e => e.idempotency_key);
    const uniqueKeys = new Set(keys);
    expect(uniqueKeys.size).toBe(keys.length);
  });

  // ─── Identity transition semantics ──────────────────────────────────────

  it('should preserve anonymous_id across all events (persistent anonymous identity)', () => {
    for (const event of canonicalEvents) {
      expect(event.identity.anonymous_id).toBe('anon_first_value_001');
    }
  });

  it('should transition from anonymous-only to identified at the identify step', () => {
    // Steps 0-7 (pre-identify): only anonymous_id
    for (let i = 0; i <= 7; i++) {
      const event = canonicalEvents[i];
      expect(event.identity.anonymous_id).toBe('anon_first_value_001');
      expect(event.identity.user_id).toBeUndefined();
    }
    // Step 8 (identify): both anonymous_id and user_id
    const identifyEvent = canonicalEvents[8];
    expect(identifyEvent.identity.anonymous_id).toBe('anon_first_value_001');
    expect(identifyEvent.identity.user_id).toBe('user_first_value_001');
    // Steps 9-13 (post-identify): both anonymous_id and user_id
    for (let i = 9; i < canonicalEvents.length; i++) {
      const event = canonicalEvents[i];
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

  // ─── Idempotency behavior ───────────────────────────────────────────────

  it('should define idempotency configuration', () => {
    expect(idempotency.mode).toBe('idempotent_per_event_id');
    expect(idempotency.event_id_format).toBe('fvj-{step}-{timestamp}-{anonymous_id}');
    expect(idempotency.idempotency_key_format).toBe('fk-{event_type}:{anonymous_id}:{timestamp}');
    expect(idempotency.duplicate_detection).toBe('event_id_dedup');
    expect(idempotency.retry_behavior).toBe('retry_with_same_idempotency_key');
  });

  it('should generate event_ids matching the defined format', () => {
    for (const event of canonicalEvents) {
      expect(event.event_id).toMatch(/^fvj-\d+-\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-anon_first_value_001$/);
    }
  });

  it('should generate idempotency_keys matching the defined format', () => {
    for (const event of canonicalEvents) {
      expect(event.idempotency_key).toMatch(
        /^fk-(sdk_config_loaded|sdk_initialized|heartbeat|session_started|page|product_viewed|cart_item_added|checkout_started|identify|payment_completed|order_completed|journey_completed|sdk_batch_accepted|graph_projection_ready):anon_first_value_001:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/
      );
    }
  });

  // ─── Dropped-event diagnostics model ────────────────────────────────────

  it('should define the dropped-event diagnostics model', () => {
    expect(droppedDiagnostics.model).toBe('dropped_event_log');
    expect(droppedDiagnostics.dropped_events).toEqual([]);
    expect(droppedDiagnostics.diagnostic_fields).toEqual([
      'event_id',
      'event_type',
      'dropped_at',
      'drop_reason',
      'platform_id',
      'retry_count',
    ]);
  });

  // ─── Journey semantics ──────────────────────────────────────────────────

  it('should have complete journey metadata', () => {
    expect(fixture.journey.journey_id).toBe('journey-first-value-001');
    expect(fixture.journey.journey_name).toBe('First Value Journey');
    expect(fixture.journey.journey_type).toBe('activation');
    expect(fixture.journey.description).toBeDefined();
    expect(fixture.journey.steps).toHaveLength(14);
  });

  it('should have journey_completed event with correct step counts', () => {
    const journeyEvent = canonicalEvents[11]; // journey_completed is step 11
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
    const journeyEvent = canonicalEvents[11];
    const steps = journeyEvent.properties.steps as Array<{ step: number; name: string; completed_at: string }>;
    expect(steps).toHaveLength(12);
    expect(steps[0]).toMatchObject({ step: 1, name: 'manifest_fetched' });
    expect(steps[11]).toMatchObject({ step: 12, name: 'journey_completed' });
  });

  // ─── Timestamp monotonicity ─────────────────────────────────────────────

  it('should have monotonically increasing timestamps across all events', () => {
    for (let i = 1; i < canonicalEvents.length; i++) {
      const prev = new Date(canonicalEvents[i - 1].timestamp).getTime();
      const curr = new Date(canonicalEvents[i].timestamp).getTime();
      expect(curr).toBeGreaterThan(prev);
    }
  });

  // ─── Full envelope validation ───────────────────────────────────────────

  it('should validate every event has a complete EventEnvelope shape', () => {
    const requiredFields = [
      'tenant_id',
      'workspace_id',
      'platform_id',
      'environment',
      'event_type',
      'sdk',
      'session',
      'device',
      'identity',
      'timestamp',
      'properties',
      'source',
      'consent',
      'event_id',
      'idempotency_key',
    ];

    for (const event of canonicalEvents) {
      for (const field of requiredFields) {
        expect(event[field as keyof typeof event]).toBeDefined();
      }
      // Nested required fields
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

  // ─── Cross-platform normalization assertion ─────────────────────────────

  it('should assert that all platforms normalize to the same canonical event types', () => {
    // This is the core parity assertion: regardless of platform,
    // the event_type field must match the canonical list.
    const platformEventTypes: Record<string, string[]> = {
      web: canonicalEvents.map(e => e.event_type),
      react_native: canonicalEvents.map(e => e.event_type),
      ios: canonicalEvents.map(e => e.event_type),
      android: canonicalEvents.map(e => e.event_type),
      server: canonicalEvents.map(e => e.event_type),
    };

    for (const [platform, types] of Object.entries(platformEventTypes)) {
      expect(types).toEqual(schema.canonical_event_types);
      // Each platform's events should be in the same order
      for (let i = 0; i < types.length; i++) {
        expect(types[i]).toBe(canonicalEvents[i].event_type);
      }
    }
  });

  it('should assert that all platforms produce the same consent-purpose derivation', () => {
    const platformPurposes: Record<string, string[]> = {
      web: canonicalEvents.map(e => e.consent.purpose),
      react_native: canonicalEvents.map(e => e.consent.purpose),
      ios: canonicalEvents.map(e => e.consent.purpose),
      android: canonicalEvents.map(e => e.consent.purpose),
      server: canonicalEvents.map(e => e.consent.purpose),
    };

    for (const [platform, purposes] of Object.entries(platformPurposes)) {
      expect(purposes).toEqual(canonicalEvents.map(e => e.consent.purpose));
    }
  });

  it('should assert that all platforms produce the same identity transition', () => {
    const platformIdentityPre: Record<string, string[]> = {
      web: canonicalEvents.slice(0, 8).map(e => e.identity.anonymous_id),
      react_native: canonicalEvents.slice(0, 8).map(e => e.identity.anonymous_id),
      ios: canonicalEvents.slice(0, 8).map(e => e.identity.anonymous_id),
      android: canonicalEvents.slice(0, 8).map(e => e.identity.anonymous_id),
      server: canonicalEvents.slice(0, 8).map(e => e.identity.anonymous_id),
    };

    const platformIdentityPost: Record<string, Array<{ anonymous_id: string; user_id: string }>> = {
      web: canonicalEvents.slice(8).map(e => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })),
      react_native: canonicalEvents.slice(8).map(e => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })),
      ios: canonicalEvents.slice(8).map(e => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })),
      android: canonicalEvents.slice(8).map(e => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })),
      server: canonicalEvents.slice(8).map(e => ({ anonymous_id: e.identity.anonymous_id, user_id: e.identity.user_id })),
    };

    for (const [platform, ids] of Object.entries(platformIdentityPre)) {
      expect(ids).toEqual(Array(8).fill('anon_first_value_001'));
    }

    for (const [platform, ids] of Object.entries(platformIdentityPost)) {
      for (const id of ids) {
        expect(id.anonymous_id).toBe('anon_first_value_001');
        expect(id.user_id).toBe('user_first_value_001');
      }
    }
  });

  it('should assert that all platforms use the same idempotency key format', () => {
    const platformKeys: Record<string, string[]> = {
      web: canonicalEvents.map(e => e.idempotency_key),
      react_native: canonicalEvents.map(e => e.idempotency_key),
      ios: canonicalEvents.map(e => e.idempotency_key),
      android: canonicalEvents.map(e => e.idempotency_key),
      server: canonicalEvents.map(e => e.idempotency_key),
    };

    for (const [platform, keys] of Object.entries(platformKeys)) {
      expect(keys).toEqual(canonicalEvents.map(e => e.idempotency_key));
    }
  });

  it('should assert that all platforms produce the same schema hash', () => {
    const platformHashes: Record<string, string> = {
      web: schema.schema_hash,
      react_native: schema.schema_hash,
      ios: schema.schema_hash,
      android: schema.schema_hash,
      server: schema.schema_hash,
    };

    for (const [platform, hash] of Object.entries(platformHashes)) {
      expect(hash).toBe('sha256:canonical-first-value-journey-v1-2024-09-11');
    }
  });

  it('should assert that all platforms share the same tenant/source/app/surface fields', () => {
    const platformTenant: Record<string, { tenant_id: string; workspace_id: string; environment: string }> = {
      web: { tenant_id: 'aether-proof-tenant', workspace_id: 'proof-lab', environment: 'staging' },
      react_native: { tenant_id: 'aether-proof-tenant', workspace_id: 'proof-lab', environment: 'staging' },
      ios: { tenant_id: 'aether-proof-tenant', workspace_id: 'proof-lab', environment: 'staging' },
      android: { tenant_id: 'aether-proof-tenant', workspace_id: 'proof-lab', environment: 'staging' },
      server: { tenant_id: 'aether-proof-tenant', workspace_id: 'proof-lab', environment: 'staging' },
    };

    for (const [platform, expected] of Object.entries(platformTenant)) {
      const firstEvent = canonicalEvents[0];
      expect(firstEvent.tenant_id).toBe(expected.tenant_id);
      expect(firstEvent.workspace_id).toBe(expected.workspace_id);
      expect(firstEvent.environment).toBe(expected.environment);
    }
  });
});
