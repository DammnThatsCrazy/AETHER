import { describe, it, expect } from 'vitest';
import type { ExplorationContextV1, FilterGroup } from '@aether/shared';
import {
  encodeExplorationContext,
  decodeExplorationContext,
  sanitizeFilterGroup,
  encodeFilterGroup,
  decodeFilterGroup,
} from './url-codec';

const TENANT = 'tenant_opaque_1';

function baseContext(overrides: Partial<ExplorationContextV1> = {}): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: TENANT, surface: 'graph' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'America/New_York' },
    ...overrides,
  };
}

function roundTrip(ctx: ExplorationContextV1): ExplorationContextV1 {
  return decodeExplorationContext(encodeExplorationContext(ctx), { tenantId: TENANT });
}

describe('url-codec round-trip', () => {
  it('round-trips a minimal context', () => {
    const ctx = baseContext();
    expect(roundTrip(ctx)).toEqual(ctx);
  });

  it('round-trips a rich context with every section populated', () => {
    const ctx = baseContext({
      anchors: [
        { kind: 'cluster', id: 'clu_123' },
        { kind: 'entity', id: 'ent-456:with:colons' },
      ],
      population: {
        logic: 'AND',
        expressions: [
          { field: 'risk.score', op: 'gte', value: 0.8 },
          { field: 'entity.type', op: 'in', value: ['human', 'agent'] },
          {
            logic: 'OR',
            expressions: [
              { field: 'geography.country', op: 'eq', value: 'US' },
              { field: 'economic.ltv_usd', op: 'between', value: { from: 10, to: 100 } },
            ],
          },
          { field: 'entity.cluster_id', op: 'exists', value: null },
        ],
      },
      temporal: {
        mode: 'as_of',
        field: 'observed_at',
        timezone: 'UTC',
        authority: 'tenant_business',
        as_of: '2026-07-01T00:00:00Z',
        range: { kind: 'instant', start: '2026-06-01T00:00:00Z', endExclusive: '2026-07-01T00:00:00Z' },
      },
      graph: {
        layers: ['H2H', 'A2A'],
        edge_types: ['PAYS', 'DELEGATES'],
        direction: 'both',
        depth: 3,
        traversal_mode: 'k_shortest',
        k: 5,
      },
      dimensions: ['events', 'wallets'],
      overlays: ['risk', 'economic'],
      presentation: {
        view: 'table',
        group_by: ['entity.type'],
        columns: ['entity.id', 'risk.score'],
        page_size: 50,
        sort: [
          { field: 'risk.score', direction: 'desc' },
          { field: 'entity.id', direction: 'asc' },
        ],
      },
      selection: {
        focused: { kind: 'entity', id: 'ent_focus' },
        selected: [
          { kind: 'entity', id: 'ent_a' },
          { kind: 'entity', id: 'ent_b' },
        ],
      },
      truth: {
        minimum_confidence: 0.6,
        allowed_dimension_states: ['ready', 'partial'],
        include_evidence: true,
        include_provenance: true,
      },
    });
    expect(roundTrip(ctx)).toEqual(ctx);
  });

  it('re-supplies tenant_id from session, never from the URL', () => {
    const ctx = baseContext();
    const query = encodeExplorationContext(ctx);
    expect(query).not.toContain(TENANT);
    const decoded = decodeExplorationContext(query, { tenantId: 'different_tenant' });
    expect(decoded.scope.tenant_id).toBe('different_tenant');
  });
});

describe('filter sanitisation (registry-only, no PII)', () => {
  it('drops expressions whose field is not in the registry', () => {
    const group: FilterGroup = {
      logic: 'AND',
      expressions: [
        { field: 'risk.score', op: 'gte', value: 0.5 },
        { field: 'user.email', op: 'eq', value: 'alice@example.com' },
      ],
    };
    const clean = sanitizeFilterGroup(group);
    expect(clean).toEqual({
      logic: 'AND',
      expressions: [{ field: 'risk.score', op: 'gte', value: 0.5 }],
    });
  });

  it('drops operators a field did not register', () => {
    const group: FilterGroup = {
      logic: 'AND',
      expressions: [
        // risk.score has no 'contains' operator
        { field: 'risk.score', op: 'contains', value: 5 },
        { field: 'risk.score', op: 'lt', value: 5 },
      ],
    };
    const clean = sanitizeFilterGroup(group);
    expect(clean?.expressions).toHaveLength(1);
    expect((clean?.expressions[0] as { op: string }).op).toBe('lt');
  });

  it('collapses a group that loses all its children to null', () => {
    const group: FilterGroup = {
      logic: 'OR',
      expressions: [{ field: 'user.ssn', op: 'eq', value: '000-00-0000' }],
    };
    expect(sanitizeFilterGroup(group)).toBeNull();
  });

  it('never emits a dropped PII value in the encoded URL', () => {
    const ctx = baseContext({
      population: {
        logic: 'AND',
        expressions: [
          { field: 'risk.score', op: 'gte', value: 0.9 },
          { field: 'user.email', op: 'eq', value: 'secret@pii.example' },
        ],
      },
    });
    const query = encodeExplorationContext(ctx);
    expect(query).not.toContain('pii.example');
    expect(query).not.toContain('user.email');
  });
});

describe('filter grammar', () => {
  it('encodes and decodes a nested group directly', () => {
    const group: FilterGroup = {
      logic: 'NOT',
      expressions: [
        { field: 'entity.tags', op: 'contains', value: 'vip' },
        {
          logic: 'AND',
          expressions: [{ field: 'graph.depth', op: 'lte', value: 4 }],
        },
      ],
    };
    expect(decodeFilterGroup(encodeFilterGroup(group))).toEqual(group);
  });
});
