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
  return decodeExplorationContext(encodeExplorationContext(ctx), { tenantId: TENANT, surface: 'graph' });
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
    expect(roundTrip(ctx)).toMatchObject({
      version: '1',
      scope: { tenant_id: TENANT, surface: 'graph' },
      anchors: ctx.anchors,
      population: ctx.population,
      temporal: ctx.temporal,
      graph: ctx.graph,
      presentation: ctx.presentation,
      selection: ctx.selection,
    });
    expect(roundTrip(ctx)).not.toHaveProperty('truth');
    expect(roundTrip(ctx)).not.toHaveProperty('dimensions');
    expect(roundTrip(ctx)).not.toHaveProperty('overlays');
  });

  it('re-supplies tenant_id from session, never from the URL', () => {
    const ctx = baseContext();
    const query = encodeExplorationContext(ctx);
    expect(query).not.toContain(TENANT);
    const decoded = decodeExplorationContext(query, { tenantId: 'different_tenant', surface: 'graph' });
    expect(decoded.scope.tenant_id).toBe('different_tenant');
    expect(decoded.scope.surface).toBe('graph');
    expect(query).not.toContain('surface=');
  });

  it('binds tenant and surface only from host defaults', () => {
    const decoded = decodeExplorationContext(
      'surface=fraud360&tenant_id=attacker&workspace_id=attacker&environment_id=prod&tmode=window',
      { tenantId: 'host-tenant', surface: 'graph' },
    );
    expect(decoded.scope).toEqual({ tenant_id: 'host-tenant', surface: 'graph' });
  });

  it('drops unknown or unsafe values instead of widening authority', () => {
    const decoded = decodeExplorationContext(
      'tmode=not-a-mode&tfield=not-a-field&tz=not-a-zone&gdir=sideways&gdepth=Infinity&gk=-1'
        + '&glayers=H2H,unknown&gedges=PAYS,UNKNOWN&pview=not-a-view&pgroup=unknown.field,entity.id'
        + '&focus=entity:ok%25ZZ,broken&sel=entity:one,entity:one',
      { tenantId: TENANT, surface: 'graph' },
    );
    expect(decoded.temporal).toEqual({ mode: 'window', field: 'occurred_at', timezone: 'UTC' });
    expect(decoded.graph).toEqual({ layers: ['H2H'], edge_types: ['PAYS'] });
    expect(decoded.presentation).toBeUndefined();
    expect(decoded.selection).toEqual({ selected: [{ kind: 'entity', id: 'one' }] });
  });

  it('bounds deep-link size and cardinality', () => {
    const anchors = Array.from({ length: 100 }, (_, i) => ({ kind: 'entity', id: `entity-${i}` }));
    const query = encodeExplorationContext(baseContext({
      anchors,
      selection: { selected: anchors },
      presentation: {
        view: 'table',
        columns: Array.from({ length: 100 }, () => 'entity.id'),
      },
    }));
    expect(query.length).toBeLessThanOrEqual(4096);
    const decoded = decodeExplorationContext(query, { tenantId: TENANT, surface: 'graph' });
    expect(decoded.anchors?.length).toBeLessThanOrEqual(32);
    expect(decoded.selection?.selected?.length).toBeLessThanOrEqual(64);
    expect(decodeExplorationContext(`${query}${'x'.repeat(5000)}`, { tenantId: TENANT, surface: 'graph' }))
      .toEqual({
        version: '1',
        scope: { tenant_id: TENANT, surface: 'graph' },
        temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
      });
  });

  it('keeps legacy safe state readable while ignoring legacy authority fields', () => {
    const decoded = decodeExplorationContext(
      'surface=graph&tenant_id=old&anchors=entity%3Alegacy&gdepth=2&pview=graph',
      { tenantId: TENANT, surface: 'timeline' },
    );
    expect(decoded.scope).toEqual({ tenant_id: TENANT, surface: 'timeline' });
    expect(decoded.anchors).toEqual([{ kind: 'entity', id: 'legacy' }]);
    expect(decoded.graph).toEqual({ depth: 2 });
    expect(decoded.presentation).toEqual({ view: 'graph' });
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

  it('never emits evidence or truth filters, even when registered', () => {
    const ctx = baseContext({
      population: {
        logic: 'AND',
        expressions: [
          { field: 'evidence.basis', op: 'eq', value: 'source' },
          { field: 'truth.confidence_min', op: 'gte', value: 0.8 },
          { field: 'risk.score', op: 'gte', value: 0.8 },
        ],
      },
    });
    const query = encodeExplorationContext(ctx);
    expect(query).not.toContain('evidence');
    expect(query).not.toContain('truth');
    expect(decodeExplorationContext(query, { tenantId: TENANT, surface: 'graph' }).population).toEqual({
      logic: 'AND',
      expressions: [{ field: 'risk.score', op: 'gte', value: 0.8 }],
    });
  });

  it('rejects arbitrary operators and malformed filter values on decode', () => {
    const query = 'pop=AND%7Bentity.id%3Aeq%3A%22ok%22%7Crisk.score%3Acontains%3A%22bad%22%7Crisk.score%3Agte%3A%22NaN%22%7D';
    expect(decodeExplorationContext(query, { tenantId: TENANT, surface: 'graph' }).population).toEqual({
      logic: 'AND',
      expressions: [{ field: 'entity.id', op: 'eq', value: 'ok' }],
    });
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
