/**
 * Profile360 store actions and pure-function unit tests.
 *
 * Covers:
 * - profile360Store state mutations via profile360Actions
 * - toTimelineEvent normalizer
 * - applyLiveMessage deduplication and prepend behaviour
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { profile360Actions, profile360Store, toTimelineEvent } from '@kyber/features/profile360/profile360-store';
import type { Profile360Payload, Profile360LiveMessage } from '@kyber/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntity(id: string) {
  const now = new Date().toISOString();
  return {
    id,
    type: 'human' as const,
    name: id,
    displayLabel: id,
    createdAt: now,
    updatedAt: now,
    health: { status: 'unknown' as const, lastChecked: now },
    trustScore: 0.5,
    riskScore: 0.2,
    anomalyScore: 0.1,
    needsHelp: false,
    tags: [],
    metadata: {},
  };
}

function makePayload(id: string): Profile360Payload {
  return {
    entity: makeEntity(id),
    sections: {},
    timeline: [],
    graph: { nodes: [], edges: [] },
    raw: {},
  };
}

function resetStore() {
  profile360Store.setState(() => ({
    entities: {},
    payloads: {},
    timelines: {},
    graphs: {},
    drillStack: [],
    highlightedNodeIds: [],
    activeTimelineFilters: [],
    websocketStatus: 'disconnected',
    liveEvents: [],
    summariesById: {},
    clustersByEntityId: {},
    journeysByEntityId: {},
    campaignsByEntityId: {},
    attributionByEntityId: {},
    walletsByEntityId: {},
    agentsByEntityId: {},
    sessionsByEntityId: {},
    devicesByEntityId: {},
    recommendationsByEntityId: {},
    qualityByEntityId: {},
    consentByEntityId: {},
    provenanceByEntityId: {},
    streamStatusByEntityId: {},
    loadingByKey: {},
    errorsByKey: {},
    staleByKey: {},
  }));
}

// ---------------------------------------------------------------------------
// Store: upsertPayload
// ---------------------------------------------------------------------------

describe('profile360Actions.upsertPayload', () => {
  beforeEach(resetStore);

  it('stores entity, timeline, and graph indexed by entity id', () => {
    const payload = makePayload('user-001');
    profile360Actions.upsertPayload(payload);

    const state = profile360Store.getState();
    expect(state.entities['user-001']).toBeDefined();
    expect(state.payloads['user-001']).toBe(payload);
    expect(state.timelines['user-001']).toEqual([]);
    expect(state.graphs['user-001']).toEqual({ nodes: [], edges: [] });
  });

  it('overwrites existing payload on repeat call', () => {
    profile360Actions.upsertPayload(makePayload('user-001'));
    const second: Profile360Payload = {
      ...makePayload('user-001'),
      entity: { ...makeEntity('user-001'), trustScore: 0.99 },
    };
    profile360Actions.upsertPayload(second);

    const state = profile360Store.getState();
    expect(state.entities['user-001']?.trustScore).toBe(0.99);
  });
});

// ---------------------------------------------------------------------------
// Store: drill stack
// ---------------------------------------------------------------------------

describe('profile360Actions drill stack', () => {
  beforeEach(resetStore);

  it('pushDrill increments depth with each push', () => {
    profile360Actions.pushDrill({ id: 'a', type: 'human', label: 'A', metadata: {} });
    profile360Actions.pushDrill({ id: 'b', type: 'wallet', label: 'B', metadata: {} });

    const { drillStack } = profile360Store.getState();
    expect(drillStack).toHaveLength(2);
    expect(drillStack[0]?.depth).toBe(0);
    expect(drillStack[1]?.depth).toBe(1);
  });

  it('popDrill removes last item', () => {
    profile360Actions.pushDrill({ id: 'a', type: 'human', label: 'A', metadata: {} });
    profile360Actions.pushDrill({ id: 'b', type: 'wallet', label: 'B', metadata: {} });
    profile360Actions.popDrill();

    const { drillStack } = profile360Store.getState();
    expect(drillStack).toHaveLength(1);
    expect(drillStack[0]?.id).toBe('a');
  });

  it('clearDrill empties the stack', () => {
    profile360Actions.pushDrill({ id: 'a', type: 'human', label: 'A', metadata: {} });
    profile360Actions.pushDrill({ id: 'b', type: 'wallet', label: 'B', metadata: {} });
    profile360Actions.clearDrill();

    expect(profile360Store.getState().drillStack).toHaveLength(0);
  });

  it('resetDrillStack empties the stack', () => {
    profile360Actions.pushDrill({ id: 'a', type: 'human', label: 'A', metadata: {} });
    profile360Actions.resetDrillStack();

    expect(profile360Store.getState().drillStack).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Store: quality and consent
// ---------------------------------------------------------------------------

describe('profile360Actions.upsertQuality', () => {
  beforeEach(resetStore);

  it('stores quality by entityId', () => {
    const quality = { readiness_status: 'release_grade', scores: { completeness: 0.95, freshness: 0.9, confidence: 0.88 }, missing_dimensions: [], stale_dimensions: [] };
    profile360Actions.upsertQuality('user-001', quality as never);

    expect(profile360Store.getState().qualityByEntityId['user-001']).toBe(quality);
  });
});

describe('profile360Actions.upsertConsent', () => {
  beforeEach(resetStore);

  it('stores consent by entityId', () => {
    const consent = { consent_status: 'granted', activation_eligibility: 'full', allowed_use_cases: ['targeting'], blocked_use_cases: [] };
    profile360Actions.upsertConsent('user-001', consent as never);

    expect(profile360Store.getState().consentByEntityId['user-001']).toBe(consent);
  });
});

// ---------------------------------------------------------------------------
// Store: loading / error / stale
// ---------------------------------------------------------------------------

describe('profile360Actions loading/error/stale', () => {
  beforeEach(resetStore);

  it('setLoading stores true/false per key', () => {
    profile360Actions.setLoading('user-001:graph', true);
    expect(profile360Store.getState().loadingByKey['user-001:graph']).toBe(true);

    profile360Actions.setLoading('user-001:graph', false);
    expect(profile360Store.getState().loadingByKey['user-001:graph']).toBe(false);
  });

  it('setError stores and clears error per key', () => {
    profile360Actions.setError('user-001:timeline', 'fetch failed');
    expect(profile360Store.getState().errorsByKey['user-001:timeline']).toBe('fetch failed');

    profile360Actions.setError('user-001:timeline', null);
    expect(profile360Store.getState().errorsByKey['user-001:timeline']).toBeNull();
  });

  it('markStale sets key to true', () => {
    profile360Actions.markStale('user-001:sessions');
    expect(profile360Store.getState().staleByKey['user-001:sessions']).toBe(true);
  });

  it('clearStale sets key to false', () => {
    profile360Actions.markStale('user-001:sessions');
    profile360Actions.clearStale('user-001:sessions');
    expect(profile360Store.getState().staleByKey['user-001:sessions']).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Store: applyLiveMessage
// ---------------------------------------------------------------------------

describe('profile360Actions.applyLiveMessage', () => {
  beforeEach(() => {
    resetStore();
    profile360Actions.upsertPayload(makePayload('user-001'));
  });

  it('prepends timeline event for the matching entity', () => {
    const event = { id: 'live-1', timestamp: new Date().toISOString(), type: 'login', title: 'Login', description: '', severity: 'info' as const, metadata: {} };
    const message: Profile360LiveMessage = { entityId: 'user-001', event };
    profile360Actions.applyLiveMessage(message);

    const timeline = profile360Store.getState().timelines['user-001'];
    expect(timeline?.[0]?.id).toBe('live-1');
  });

  it('dedupes graph nodes by id', () => {
    const node = { id: 'wallet-x', type: 'wallet' as const, label: 'Wallet X', metadata: {} };
    const message: Profile360LiveMessage = { entityId: 'user-001', node };
    profile360Actions.applyLiveMessage(message);
    profile360Actions.applyLiveMessage(message);

    const nodes = profile360Store.getState().graphs['user-001']?.nodes ?? [];
    const walletXCount = nodes.filter((n) => n.id === 'wallet-x').length;
    expect(walletXCount).toBe(1);
  });

  it('dedupes graph edges by id', () => {
    const edge = { id: 'edge-x', source: 'user-001', target: 'wallet-x', type: 'OWNS', weight: 1, label: 'owns', metadata: {} };
    const message: Profile360LiveMessage = { entityId: 'user-001', edge };
    profile360Actions.applyLiveMessage(message);
    profile360Actions.applyLiveMessage(message);

    const edges = profile360Store.getState().graphs['user-001']?.edges ?? [];
    const edgeXCount = edges.filter((e) => e.id === 'edge-x').length;
    expect(edgeXCount).toBe(1);
  });

  it('ignores message with no entityId', () => {
    const before = profile360Store.getState().liveEvents.length;
    profile360Actions.applyLiveMessage({ entityId: '' });
    expect(profile360Store.getState().liveEvents.length).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// toTimelineEvent normalizer
// ---------------------------------------------------------------------------

describe('toTimelineEvent', () => {
  it('uses id field when present', () => {
    const result = toTimelineEvent({ id: 'evt-abc', timestamp: '2026-01-01T00:00:00Z', type: 'login' }, 'fallback');
    expect(result.id).toBe('evt-abc');
  });

  it('falls back to provided id when input has no id', () => {
    const result = toTimelineEvent({ type: 'login' }, 'fallback-id');
    expect(result.id).toBe('fallback-id');
  });

  it('normalizes event_type as type', () => {
    const result = toTimelineEvent({ event_type: 'purchase', id: 'e1' }, 'e1');
    expect(result.type).toBe('purchase');
  });

  it('normalizes created_at as timestamp', () => {
    const result = toTimelineEvent({ id: 'e1', created_at: '2026-06-01T00:00:00Z' }, 'e1');
    expect(result.timestamp).toBe('2026-06-01T00:00:00Z');
  });

  it('defaults severity to info when unrecognized value', () => {
    const result = toTimelineEvent({ id: 'e1', severity: 'CRITICAL' }, 'e1');
    expect(result.severity).toBe('info');
  });

  it('accepts valid severity values', () => {
    for (const sev of ['P0', 'P1', 'P2', 'P3', 'info'] as const) {
      const result = toTimelineEvent({ id: 'e1', severity: sev }, 'e1');
      expect(result.severity).toBe(sev);
    }
  });

  it('uses metadata field for metadata', () => {
    const result = toTimelineEvent({ id: 'e1', metadata: { key: 'val' } }, 'e1');
    expect(result.metadata).toEqual({ key: 'val' });
  });

  it('falls back to properties when metadata absent', () => {
    const result = toTimelineEvent({ id: 'e1', properties: { key: 'prop' } }, 'e1');
    expect(result.metadata).toEqual({ key: 'prop' });
  });
});
