import { describe, expect, it, vi } from 'vitest';
import type { ZodType } from 'zod';

// Each case pins a page normaliser to the shape the real backend route returns.

const h = vi.hoisted(() => ({ payload: undefined as unknown }));
vi.mock('@aether-app/lib/api/rest/client', () => ({
  restClient: {
    get: (_url: string, schema: ZodType) => Promise.resolve(schema.parse(h.payload)),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from '@aether-app/lib/api/endpoints';
import { matchesQuery } from '@aether-app/features/users/use-users';
import { identifierGroups, profileNetwork } from '@aether-app/pages/user-profile/profile-model';
import { compactMoney, dailySeries, inOneCurrency, parseValueEvents, SERIES_MAX_DAYS } from '@aether-app/pages/value-review/value-model';
import { nodeTime, objectLinks } from '@aether-app/pages/explore/explore-model';
import { circularMeanLongitude } from '@aether-app/pages/explore/explore-visuals';

describe('GET /v1/campaigns client', () => {
  it('reads the keyset envelope the route returns, without an APIResponse status', async () => {
    h.payload = { data: [{ id: 'c1' }, { id: 'c2' }], pagination: { limit: 2, next_cursor: '2026-10-01', has_more: true } };
    await expect(api.campaigns.list({ limit: 2 })).resolves.toEqual({
      campaigns: [{ id: 'c1' }, { id: 'c2' }],
      total: 2,
      has_more: true,
      next_cursor: '2026-10-01',
    });
  });

  it('reports a last page as complete', async () => {
    h.payload = { data: [], pagination: { limit: 50, next_cursor: null, has_more: false } };
    await expect(api.campaigns.list()).resolves.toMatchObject({ total: 0, has_more: false, next_cursor: null });
  });
});

describe('GET /v1/entities client (Profiles)', () => {
  it('reads the {entities, count} envelope the route returns', async () => {
    h.payload = { status: 'success', timestamp: '2026-10-22T00:00:00Z', data: { entities: [{ entity_id: 'e1' }], count: 1 } };
    await expect(api.entities.list({ limit: 100 })).resolves.toEqual({ entities: [{ entity_id: 'e1' }], total: 1, has_more: false });
  });

  it('reports another page when the route returns next_offset', async () => {
    h.payload = { status: 'success', timestamp: '2026-10-22T00:00:00Z', data: { entities: [], count: 0, next_offset: 100 } };
    await expect(api.entities.list({ limit: 100, offset: 0 })).resolves.toMatchObject({ has_more: true });
  });

  it('matches a search on name, email or id without a search route', () => {
    const row = { id: 'ent_42', displayName: 'Jordan Lee', email: 'jordan@northpeak.co' };
    expect(matchesQuery(row, 'jordan')).toBe(true);
    expect(matchesQuery(row, 'northpeak')).toBe(true);
    expect(matchesQuery(row, 'ent_4')).toBe(true);
    expect(matchesQuery(row, 'nobody')).toBe(false);
  });
});

describe('Profile 360 normalisers', () => {
  it('unwraps /v1/profile/{id}/identifiers and keeps the resolver kind names', () => {
    const groups = identifierGroups({
      user_id: 'u1',
      identifiers: { wallets: ['0xabc'], emails: ['a@b.co'], phones: ['+15550100'], devices: [], sessions: ['s1'], social: ['@handle'] },
    });
    expect(groups.map(g => g.kind)).toEqual(['emails', 'phones', 'wallets', 'social', 'sessions']);
    expect(groups.find(g => g.kind === 'social')?.values).toEqual(['@handle']);
  });

  it('reads /v1/entities/{id}/graph edges (source_/target_entity_id, edge_type)', () => {
    const net = profileNetwork(
      { entity_id: 'u1', edges: [{ id: 'e1', source_entity_id: 'u1', target_entity_id: 'w1', edge_type: 'shares_wallet', confidence: 0.9 }] },
      'u1',
    );
    expect(net.links).toHaveLength(1);
    expect(net.links[0]).toMatchObject({ id: 'e1', other: 'w1', relation: 'shares_wallet', confidence: 0.9 });
    expect(net.nodes.map(n => n.id)).toEqual(['w1']);
  });
});

describe('Value aggregation', () => {
  const event = (amount: number | null, currency: string | null, at = '2026-10-01T12:00:00Z') => ({
    value_event_id: `${amount}-${currency}-${at}`,
    source_type: 'outcome',
    value_type: 'retained_revenue',
    value_amount: amount,
    currency,
    occurred_at: at,
  });

  it('never adds amounts across currencies', () => {
    const events = parseValueEvents({ items: [event(100, 'USD'), event(50, 'usd'), event(70, 'EUR')] });
    const read = inOneCurrency(events);
    expect(read.currency).toBe('USD');
    expect(read.setAside).toBe(1);
    expect(read.otherCurrencies).toEqual(['EUR']);
    expect(read.events.reduce((a, e) => a + (e.amount ?? 0), 0)).toBe(150);
  });

  it('leaves a single-currency read untouched and labels non-USD amounts', () => {
    const read = inOneCurrency(parseValueEvents({ items: [event(1200, 'EUR'), event(null, 'EUR')] }));
    expect(read).toMatchObject({ currency: 'EUR', setAside: 0 });
    expect(compactMoney(1200, read.currency)).toBe('EUR 1.2k');
    expect(compactMoney(1200)).toBe('$1.2k');
  });

  it('keeps the most recent days when the span exceeds the series cap', () => {
    const series = dailySeries(parseValueEvents({ items: [event(1, 'USD', '2020-01-01T12:00:00Z'), event(5, 'USD', '2026-10-01T12:00:00Z')] }));
    expect(series).toHaveLength(SERIES_MAX_DAYS);
    expect(series.at(-1)).toMatchObject({ day: '2026-10-01', total: 5 });
  });
});

describe('Graph workspace', () => {
  it('reads the canonical camelCase node creation time', () => {
    expect(nodeTime({ id: 'n1', label: 'n1', kind: 'entity', metadata: { createdAt: '2026-10-01T00:00:00Z' } })).toBe(Date.parse('2026-10-01T00:00:00Z'));
  });

  it('links a cluster member to the cluster that contains it', () => {
    const links = objectLinks(
      { id: 'n1', label: 'n1', kind: 'wallet', metadata: {} },
      [{ id: 'cl-7', label: 'cluster', nodeIds: ['n0', 'n1'], size: 2 }],
    );
    expect(links).toContainEqual({ label: 'Open cluster', to: '/clusters/cl-7' });
  });

  it('centres places either side of the antimeridian at 180°', () => {
    expect(Math.abs(circularMeanLongitude([170, -170]))).toBeCloseTo(180);
    expect(circularMeanLongitude([10, 30])).toBeCloseTo(20);
  });
});
