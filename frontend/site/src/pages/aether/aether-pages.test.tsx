import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import { MANAGED_CONNECTORS } from '@site/site/connectors';

vi.stubEnv('VITE_SITE_OLYMPUS_URL', 'https://olympuslabsml.com');
vi.stubEnv('VITE_SITE_AETHER_URL', 'https://aether.olympuslabsml.com');

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App site="aether" />
    </MemoryRouter>,
  );

const INNER = [
  { path: '/how-it-works', title: 'How it works — Aether', nav: 'How it works', toc: ['pipeline', 'layers', 'states', 'authority', 'example'] },
  { path: '/connections', title: 'Connections — Aether', nav: 'Connections', toc: ['paths', 'catalog', 'carries', 'readiness'] },
  { path: '/security', title: 'Security and trust — Aether', nav: 'Security', toc: ['controls', 'keys', 'data', 'deploy', 'limits'] },
  { path: '/procurement', title: 'Procurement — Aether', nav: null, toc: ['process', 'commercial', 'documents', 'faq'] },
];

describe.each(INNER)('Aether $path', ({ path, title, nav, toc }) => {
  it('renders with its title, header state, and on-page sections', () => {
    renderAt(path);
    expect(document.title).toBe(title);
    if (nav) {
      const primary = screen.getByRole('navigation', { name: 'Primary' });
      expect(within(primary).getByRole('link', { name: nav }).getAttribute('aria-current')).toBe('page');
    }
    const onPage = screen.getByRole('navigation', { name: 'On this page' });
    for (const id of toc) {
      expect(within(onPage).getAllByRole('link').some((a) => a.getAttribute('href') === `#${id}`)).toBe(true);
      expect(document.getElementById(id)).not.toBeNull();
    }
  });
});

describe('Aether Home', () => {
  it('switches About tabs and product layers', async () => {
    renderAt('/');
    const tabs = screen.getByRole('tablist', { name: 'About Aether' });
    expect(within(tabs).getByRole('tab', { name: /What it is/ }).getAttribute('aria-selected')).toBe('true');
    await userEvent.click(within(tabs).getByRole('tab', { name: /How it works/ }));
    expect(screen.getByText('layer 3 / 5')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /Aether Events/ }));
    expect(screen.getByText('layer 1 / 5')).toBeTruthy();
  });

  it('states the connector count from the catalog', () => {
    renderAt('/');
    expect(MANAGED_CONNECTORS).toHaveLength(13);
    const term = screen.getByText('managed connectors');
    expect(term.parentElement?.querySelector('dd')?.textContent).toBe(String(MANAGED_CONNECTORS.length));
  });
});

describe('Profile 360', () => {
  it('labels its data as synthetic and moves between sections', async () => {
    renderAt('/');
    expect(screen.getByTitle('Illustrative data — not a customer record').textContent).toBe('synthetic');
    const sections = screen.getByRole('tablist', { name: 'Profile sections' });
    await userEvent.click(screen.getByRole('button', { name: /See why/ }));
    expect(within(sections).getByRole('tab', { name: /Risk/ }).getAttribute('aria-selected')).toBe('true');
    await userEvent.click(screen.getByRole('button', { name: /Mark reviewed/ }));
    expect(screen.getByText('✓ reviewed by you · just now')).toBeTruthy();
  });

  it('filters relationships and searches the profile', async () => {
    renderAt('/');
    await userEvent.click(screen.getByRole('button', { name: /Search this profile/ }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Search this profile' }), 'percival{Enter}');
    const sections = screen.getByRole('tablist', { name: 'Profile sections' });
    expect(within(sections).getByRole('tab', { name: /Relationships/ }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('button', { name: /Humans 3/ }).getAttribute('aria-pressed')).toBe('true');
    const panel = document.getElementById('p360-panel')!;
    expect(within(panel).getByText('Percival')).toBeTruthy();
    expect(within(panel).queryByText('Ptolemy')).toBeNull();
  });
});

describe('Pricing', () => {
  afterEach(() => {
    vi.stubEnv('VITE_PUBLISH_PRICES', '');
  });

  it('holds prices back unless the build publishes them', () => {
    renderAt('/pricing');
    expect(screen.queryByText('$299')).toBeNull();
    expect(screen.getAllByText('On request').length).toBeGreaterThan(0);
    expect(screen.queryByRole('radiogroup', { name: 'Billing interval' })).toBeNull();
  });

  it('shows catalog prices and carries plan and interval to signup', async () => {
    vi.stubEnv('VITE_PUBLISH_PRICES', 'true');
    renderAt('/pricing');
    expect(screen.getAllByText('$299').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('radio', { name: 'Annual' }));
    expect(screen.getAllByText('$3,050').length).toBeGreaterThan(0);
    const choose = screen.getAllByRole('link', { name: 'Choose Beta' })[0]!;
    expect(choose.getAttribute('href')).toBe('/app/signup?plan=beta&interval=annual');
  });
});
