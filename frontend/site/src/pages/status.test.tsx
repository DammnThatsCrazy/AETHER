import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import { checkHealth, fillDays, parseHistory, uptime } from '@site/site/status';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

const renderStatus = () =>
  render(
    <MemoryRouter initialEntries={['/status']}>
      <App site="aether" />
    </MemoryRouter>,
  );

describe('status data', () => {
  it('never reports operational without a source', async () => {
    const snap = await checkHealth('');
    expect(snap.source).toBe('unconfigured');
    expect(snap.state).toBe('unknown');
  });

  it('maps backend component states', async () => {
    const snap = await checkHealth('https://api.test/v1/health', () =>
      json({ status: 'degraded', components: { ingestion: { status: 'degraded' }, identity: { status: 'healthy' }, x: { status: 'weird' } } }),
    );
    expect(snap.state).toBe('degraded');
    expect(Object.fromEntries(snap.components.map((c) => [c.key, c.state]))).toEqual({ ingestion: 'degraded', identity: 'operational', x: 'unknown' });
  });

  it('reports an unreachable endpoint as such', async () => {
    const snap = await checkHealth('https://api.test/v1/health', () => Promise.reject(new TypeError('network')));
    expect(snap.source).toBe('unreachable');
  });

  it('treats missing and malformed history days as no data, distinct from zero uptime', () => {
    const hist = parseHistory({
      components: [{ name: 'api', days: [{ date: '2026-09-25', status: 'outage', uptime_pct: 0 }, { date: '2026-09-26', status: 'bogus', uptime_pct: 100 }] }],
      incidents: [{ id: 'i', title: 'T', started_at: '2026-09-25T01:00:00Z' }, { title: 'missing id' }],
    });
    const days = fillDays(hist.components.api, 5, new Date('2026-09-26T12:00:00Z'));
    expect(days.map((d) => d.status)).toEqual(['no_data', 'no_data', 'no_data', 'outage', 'no_data']);
    expect(uptime(days)).toBe(0);
    expect(uptime(fillDays(undefined, 5, new Date()))).toBeNull();
    expect(hist.incidents).toHaveLength(1);
  });
});

describe('status page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubEnv('VITE_STATUS_API_URL', '');
    vi.stubEnv('VITE_STATUS_HISTORY_URL', '');
  });

  it('says the monitor is not configured instead of showing green', async () => {
    renderStatus();
    expect((await screen.findByRole('status')).textContent).toContain('Status not yet verified');
    expect(screen.getByText('No component data')).toBeTruthy();
    expect(screen.queryByText('All systems operational')).toBeNull();
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#main');
    expect(screen.getByRole('main').getAttribute('tabindex')).toBe('-1');
  });

  it('renders live components with 90 history bars each', async () => {
    vi.stubEnv('VITE_STATUS_API_URL', 'https://api.test/v1/health');
    vi.stubEnv('VITE_STATUS_HISTORY_URL', 'https://api.test/v1/status/history');
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url.includes('history')
          ? json({ components: [{ name: 'identity', days: [] }], incidents: [] })
          : json({ status: 'healthy', components: { identity: { status: 'healthy' }, ingestion: { status: 'healthy' } } }),
      ),
    );
    renderStatus();
    expect((await screen.findByText('All systems operational')).closest('h1')).toBeTruthy();
    const bars = screen.getByRole('img', { name: /Identity & graph: 90-day history, no history yet/ });
    expect(bars.children).toHaveLength(90);
    expect(screen.getByText('No incidents reported in the last 90 days.')).toBeTruthy();
    const product = screen.getByText('Customer-visible product').closest('details')!;
    expect(within(product).getByText('all 1 operational')).toBeTruthy();
  });

  it('shows live state even when the history feed never answers', async () => {
    vi.stubEnv('VITE_STATUS_API_URL', 'https://api.test/v1/health');
    vi.stubEnv('VITE_STATUS_HISTORY_URL', 'https://api.test/v1/status/history');
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url.includes('history') ? new Promise<Response>(() => {}) : json({ status: 'healthy', components: {} }),
      ),
    );
    renderStatus();
    expect((await screen.findByText('All systems operational')).closest('h1')).toBeTruthy();
  });
});
